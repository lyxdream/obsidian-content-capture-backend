from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from script.feishu_inbox import append_feishu_inbox, extract_douyin_links, read_jsonl
from script.feishu_reply import ReplySender, queued_reply_text, tenant_access_token, try_send_reply


@dataclass(frozen=True)
class FeishuPollSummary:
    scanned_messages: int = 0
    queued_messages: int = 0
    queued_links: int = 0
    reply_sent: int = 0
    reply_failed: int = 0


def _message_text(item: dict[str, Any]) -> str:
    content = ((item.get("body") or {}).get("content")) or ""
    if not isinstance(content, str):
        return ""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return content.strip()
    return str(payload.get("text") or payload.get("content") or "").strip()


def _message_payload_from_item(item: dict[str, Any], text: str) -> dict[str, Any]:
    return {
        "header": {"event_type": "im.message.receive_v1.api_poll"},
        "event": {
            "message": {
                "message_id": item.get("message_id"),
                "chat_id": item.get("chat_id"),
                "chat_type": item.get("chat_type"),
                "create_time": item.get("create_time"),
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
            "sender": item.get("sender") or {},
        },
    }


def _existing_message_ids(inbox_dir: Path | None) -> set[str]:
    root = inbox_dir
    if root is None:
        return set()
    inbox_path = root / "feishu-events.jsonl"
    return {str(item.get("message_id")) for item in read_jsonl(inbox_path) if item.get("message_id")}


def _within_lookback(item: dict[str, Any], *, lookback_seconds: int) -> bool:
    if lookback_seconds <= 0:
        return True
    create_time = item.get("create_time")
    if not create_time:
        return False
    try:
        message_time = int(create_time) / 1000
    except (TypeError, ValueError):
        return False
    return message_time >= time.time() - lookback_seconds


def queue_feishu_message_items(
    items: list[dict[str, Any]],
    *,
    inbox_dir: Path,
    lookback_seconds: int = 3600,
    reply_sender: ReplySender | None = None,
    now: datetime | None = None,
) -> FeishuPollSummary:
    existing_ids = _existing_message_ids(inbox_dir)
    scanned = queued_messages = queued_links = reply_sent = reply_failed = 0
    received_at = now or datetime.now(timezone.utc)

    # API returns newest first when sort_type=ByCreateTimeDesc. Queue oldest first.
    for item in reversed(items):
        scanned += 1
        message_id = str(item.get("message_id") or "")
        if not message_id or message_id in existing_ids:
            continue
        if (item.get("sender") or {}).get("sender_type") != "user":
            continue
        if not _within_lookback(item, lookback_seconds=lookback_seconds):
            continue

        text = _message_text(item)
        links = extract_douyin_links(text)
        if not links:
            continue

        payload = _message_payload_from_item(item, text)
        _inbox_path, record = append_feishu_inbox(
            payload,
            inbox_dir=inbox_dir,
            text=text,
            links=links,
            now=received_at,
        )
        existing_ids.add(message_id)
        queued_messages += 1
        queued_links += len(links)

        reply_error = try_send_reply(
            record.get("message_id"),
            queued_reply_text(link_count=len(links)),
            reply_sender=reply_sender,
        )
        if reply_error:
            reply_failed += 1
        else:
            reply_sent += 1

    return FeishuPollSummary(scanned, queued_messages, queued_links, reply_sent, reply_failed)


def fetch_feishu_chat_messages(chat_id: str, *, page_size: int = 20) -> list[dict[str, Any]]:
    response = requests.get(
        "https://open.feishu.cn/open-apis/im/v1/messages",
        headers={"Authorization": f"Bearer {tenant_access_token()}"},
        params={
            "container_id_type": "chat",
            "container_id": chat_id,
            "page_size": page_size,
            "sort_type": "ByCreateTimeDesc",
        },
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(str(payload.get("msg") or payload))
    return list((payload.get("data") or {}).get("items") or [])


def poll_feishu_chat_once(
    *,
    chat_id: str,
    inbox_dir: Path,
    page_size: int = 20,
    lookback_seconds: int = 3600,
    reply_sender: ReplySender | None = None,
) -> FeishuPollSummary:
    items = fetch_feishu_chat_messages(chat_id, page_size=page_size)
    return queue_feishu_message_items(
        items,
        inbox_dir=inbox_dir,
        lookback_seconds=lookback_seconds,
        reply_sender=reply_sender,
    )
