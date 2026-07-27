from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from typing import Any

import requests


ReplySender = Callable[[str, str], None]

_TOKEN_CACHE: dict[str, Any] = {"token": "", "expires_at": 0.0}
DEFAULT_FEISHU_APP_ID = "cli_aaab1c2d2c785bfc"


class FeishuReplyError(RuntimeError):
    pass


def _env(name: str) -> str:
    if name == "FEISHU_APP_ID":
        return os.environ.get(name, DEFAULT_FEISHU_APP_ID).strip()
    return os.environ.get(name, "").strip()


def tenant_access_token() -> str:
    now = time.time()
    cached = str(_TOKEN_CACHE.get("token") or "")
    if cached and float(_TOKEN_CACHE.get("expires_at") or 0) > now + 60:
        return cached

    app_id = _env("FEISHU_APP_ID")
    app_secret = _env("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        raise FeishuReplyError("缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET")

    response = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise FeishuReplyError(str(payload.get("msg") or payload))

    token = str(payload.get("tenant_access_token") or "")
    if not token:
        raise FeishuReplyError("飞书 tenant_access_token 为空")
    expire = int(payload.get("expire") or 7200)
    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["expires_at"] = now + expire
    return token


def send_feishu_text_reply(message_id: str, text: str) -> None:
    if not message_id:
        raise FeishuReplyError("缺少 message_id，无法回复飞书消息")
    if _env("FEISHU_REPLY_DISABLED").lower() in {"1", "true", "yes"}:
        return

    token = tenant_access_token()
    response = requests.post(
        f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
        headers={"Authorization": f"Bearer {token}"},
        json={"msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise FeishuReplyError(str(payload.get("msg") or payload))


def try_send_reply(
    message_id: str | None,
    text: str,
    *,
    reply_sender: ReplySender | None = None,
) -> str | None:
    if not message_id:
        return "missing message_id"
    sender = reply_sender or send_feishu_text_reply
    try:
        sender(str(message_id), text)
    except Exception as e:
        return str(e)
    return None


def queued_reply_text(*, link_count: int) -> str:
    return f"已接收：收到 {link_count} 个抖音链接，已进入短视频收件箱。处理完成后我会再回复。"


def processed_reply_text(result: dict[str, Any]) -> str:
    status = result.get("status")
    link = str(result.get("link") or "")
    if status in {"processed", "dry_run"}:
        report = result.get("study_report")
        extra = f"\n学习报告：{report}" if report else ""
        return f"已处理完毕：{link}{extra}"
    if status == "failed":
        return f"处理失败：{link}\n原因：{result.get('error') or '未知错误'}"
    if status == "skipped":
        return f"已处理过，跳过重复链接：{link}"
    return f"处理状态更新：{status or 'unknown'} {link}".strip()
