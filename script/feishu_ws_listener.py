#!/usr/bin/env python3
"""Feishu long-connection listener for the mobile video inbox."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from script.feishu_inbox import (
    append_feishu_inbox,
    extract_douyin_links,
    extract_message_text,
)
from script.feishu_reply import ReplySender, queued_reply_text, try_send_reply


@dataclass(frozen=True)
class ListenerQueueResult:
    queued: int
    inbox_path: Path | None
    record: dict[str, Any] | None
    reply_error: str | None = None
    reply_sent: bool = False


def _sdk_event_to_payload(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return data

    try:
        import lark_oapi as lark
    except ImportError as e:  # pragma: no cover - covered by CLI validation
        raise RuntimeError("缺少 lark-oapi，请先执行 pip install -r requirements.txt") from e

    raw = lark.JSON.marshal(data)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def queue_message_event(
    data: Any,
    *,
    inbox_dir: Path | None = None,
    reply_sender: ReplySender | None = None,
) -> ListenerQueueResult:
    payload = _sdk_event_to_payload(data)
    event = payload.get("event") or {}
    text = extract_message_text(event)
    links = extract_douyin_links(text)
    if not links:
        return ListenerQueueResult(queued=0, inbox_path=None, record=None)

    inbox_path, record = append_feishu_inbox(
        payload,
        inbox_dir=inbox_dir,
        text=text,
        links=links,
    )
    reply_error = try_send_reply(
        record.get("message_id"),
        queued_reply_text(link_count=len(links)),
        reply_sender=reply_sender,
    )
    return ListenerQueueResult(
        queued=len(links),
        inbox_path=inbox_path,
        record=record,
        reply_error=reply_error,
        reply_sent=reply_error is None,
    )


def _env_required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"缺少环境变量 {name}")
    return value


def _log_queue_result(result: ListenerQueueResult) -> None:
    if result.queued:
        links = ", ".join(result.record.get("links", [])) if result.record else ""
        reply = f" reply_error={result.reply_error}" if result.reply_error else " reply=sent"
        print(f"queued={result.queued} links={links}{reply}", flush=True)
    else:
        print("queued=0 message=no-douyin-link", flush=True)


def start_listener(app_id: str, app_secret: str, *, log_level_name: str = "INFO") -> None:
    try:
        import lark_oapi as lark
    except ImportError as e:
        raise SystemExit("缺少 lark-oapi，请先执行 pip install -r requirements.txt") from e

    log_level = getattr(lark.LogLevel, log_level_name.upper(), lark.LogLevel.INFO)

    def on_message(data: Any) -> None:
        _log_queue_result(queue_message_event(data))

    try:
        builder = lark.EventDispatcherHandler.builder("", "", log_level)
    except TypeError:
        builder = lark.EventDispatcherHandler.builder("", "")

    event_handler = builder.register_p2_im_message_receive_v1(on_message).build()
    client = lark.ws.Client(
        app_id,
        app_secret,
        event_handler=event_handler,
        log_level=log_level,
    )
    print("feishu-ws-listener=starting event=im.message.receive_v1", flush=True)
    client.start()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动飞书长连接，接收马哥消息并写入短视频收件箱。")
    parser.add_argument("--app-id", default=os.environ.get("FEISHU_APP_ID", ""))
    parser.add_argument("--app-secret", default=os.environ.get("FEISHU_APP_SECRET", ""))
    parser.add_argument("--log-level", default=os.environ.get("FEISHU_LOG_LEVEL", "INFO"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    app_id = args.app_id.strip() or _env_required("FEISHU_APP_ID")
    app_secret = args.app_secret.strip() or _env_required("FEISHU_APP_SECRET")
    start_listener(app_id, app_secret, log_level_name=args.log_level)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
