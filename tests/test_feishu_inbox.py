from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from script.feishu_inbox import (
    default_inbox_files,
    process_inbox_once,
    read_jsonl,
)
from script.feishu_poller import queue_feishu_message_items
from script.feishu_ws_listener import queue_message_event
from web.app import app


def _message_payload(text: str, message_id: str = "om_test") -> dict:
    return {
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "message": {
                "message_id": message_id,
                "content": json.dumps({"text": text}, ensure_ascii=False),
            }
        },
    }


class FeishuInboxTest(unittest.TestCase):
    def test_feishu_callback_queues_douyin_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "VIDEO_INBOX_DIR": tmp,
                "FEISHU_EVENT_PATH_SECRET": "secret-path",
                "FEISHU_VERIFICATION_TOKEN": "",
            }
            with patch.dict(os.environ, env, clear=False):
                client = app.test_client()
                response = client.post(
                    "/api/feishu/events/secret-path",
                    json=_message_payload(
                        "复制打开抖音 https://v.douyin.com/JLbVVYlIZRk/ 看看"
                    ),
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["queued"], 1)

            inbox_path, _ = default_inbox_files(Path(tmp))
            records = read_jsonl(inbox_path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["status"], "queued")
            self.assertEqual(records[0]["message_id"], "om_test")
            self.assertEqual(records[0]["links"], ["https://v.douyin.com/JLbVVYlIZRk/"])

    def test_worker_dry_run_records_each_unprocessed_link_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inbox_path, processed_path = default_inbox_files(Path(tmp))
            record = {
                "source": "feishu",
                "status": "queued",
                "message_id": "om_test",
                "links": [
                    "https://v.douyin.com/one/",
                    "https://v.douyin.com/two/",
                ],
                "text": "两个链接",
            }
            inbox_path.write_text(
                json.dumps(record, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            first = process_inbox_once(inbox_path, processed_path, dry_run=True)
            second = process_inbox_once(inbox_path, processed_path, dry_run=True)

            self.assertEqual(first.scanned_records, 1)
            self.assertEqual(first.created_results, 2)
            self.assertEqual(second.created_results, 0)

            processed = read_jsonl(processed_path)
            self.assertEqual([item["status"] for item in processed], ["dry_run", "dry_run"])
            self.assertEqual(
                [item["link"] for item in processed],
                ["https://v.douyin.com/one/", "https://v.douyin.com/two/"],
            )

    def test_worker_skips_link_already_processed_from_another_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inbox_path, processed_path = default_inbox_files(Path(tmp))
            inbox_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "source": "feishu",
                                "status": "queued",
                                "message_id": "om_new",
                                "links": ["https://v.douyin.com/repeat/"],
                                "text": "重复链接",
                            },
                            ensure_ascii=False,
                        ),
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            processed_path.write_text(
                json.dumps(
                    {
                        "source": "feishu",
                        "source_record_id": "om_old",
                        "message_id": "om_old",
                        "link": "https://v.douyin.com/repeat/",
                        "status": "processed",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            summary = process_inbox_once(inbox_path, processed_path, dry_run=True)

            self.assertEqual(summary.created_results, 0)
            self.assertEqual(summary.skipped_results, 1)

    def test_ws_listener_queues_same_inbox_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = queue_message_event(
                _message_payload(
                    "手机发给马哥 https://v.douyin.com/wsone/ 入库",
                    message_id="om_ws",
                ),
                inbox_dir=Path(tmp),
            )

            self.assertEqual(result.queued, 1)
            self.assertIsNotNone(result.inbox_path)
            self.assertEqual(result.record["message_id"], "om_ws")
            self.assertEqual(result.record["links"], ["https://v.douyin.com/wsone/"])

            inbox_path, _ = default_inbox_files(Path(tmp))
            records = read_jsonl(inbox_path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["source"], "feishu")

    def test_ws_listener_replies_after_message_is_queued(self) -> None:
        replies: list[tuple[str, str]] = []

        with tempfile.TemporaryDirectory() as tmp:
            result = queue_message_event(
                _message_payload(
                    "手机发给马哥 https://v.douyin.com/wsone/ 入库",
                    message_id="om_ws_reply",
                ),
                inbox_dir=Path(tmp),
                reply_sender=lambda message_id, text: replies.append((message_id, text)),
            )

            self.assertEqual(result.queued, 1)
            self.assertTrue(result.reply_sent)
            self.assertIsNone(result.reply_error)
            self.assertEqual(len(replies), 1)
            self.assertEqual(replies[0][0], "om_ws_reply")
            self.assertIn("已接收", replies[0][1])
            self.assertIn("1", replies[0][1])

    def test_ws_listener_ignores_messages_without_douyin_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = queue_message_event(
                _message_payload("普通聊天，不入库", message_id="om_empty"),
                inbox_dir=Path(tmp),
            )

            self.assertEqual(result.queued, 0)
            self.assertIsNone(result.inbox_path)
            inbox_path, _ = default_inbox_files(Path(tmp))
            self.assertEqual(read_jsonl(inbox_path), [])

    def test_worker_replies_after_processed_link_finishes(self) -> None:
        replies: list[tuple[str, str]] = []

        with tempfile.TemporaryDirectory() as tmp:
            inbox_path, processed_path = default_inbox_files(Path(tmp))
            inbox_path.write_text(
                json.dumps(
                    {
                        "source": "feishu",
                        "status": "queued",
                        "message_id": "om_done",
                        "links": ["https://v.douyin.com/done/"],
                        "text": "处理完成回执",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            summary = process_inbox_once(
                inbox_path,
                processed_path,
                dry_run=True,
                reply_sender=lambda message_id, text: replies.append((message_id, text)),
            )

            self.assertEqual(summary.created_results, 1)
            self.assertEqual(summary.reply_sent, 1)
            self.assertEqual(summary.reply_failed, 0)
            self.assertEqual(len(replies), 1)
            self.assertEqual(replies[0][0], "om_done")
            self.assertIn("已处理完毕", replies[0][1])
            self.assertIn("https://v.douyin.com/done/", replies[0][1])

    def test_feishu_poller_backfills_recent_chat_message(self) -> None:
        replies: list[tuple[str, str]] = []

        with tempfile.TemporaryDirectory() as tmp:
            now_ms = int(time.time() * 1000)
            summary = queue_feishu_message_items(
                [
                    {
                        "message_id": "om_polled",
                        "chat_id": "oc_test",
                        "create_time": str(now_ms),
                        "msg_type": "text",
                        "sender": {"sender_type": "user"},
                        "body": {
                            "content": json.dumps(
                                {
                                    "text": "飞书 API 兜底 https://v.douyin.com/polled/ 入库",
                                },
                                ensure_ascii=False,
                            )
                        },
                    }
                ],
                inbox_dir=Path(tmp),
                reply_sender=lambda message_id, text: replies.append((message_id, text)),
            )

            self.assertEqual(summary.queued_messages, 1)
            self.assertEqual(summary.queued_links, 1)
            self.assertEqual(summary.reply_sent, 1)
            self.assertEqual(replies[0][0], "om_polled")
            self.assertIn("已接收", replies[0][1])

            inbox_path, _processed_path = default_inbox_files(Path(tmp))
            records = read_jsonl(inbox_path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["message_id"], "om_polled")
            self.assertEqual(records[0]["chat_id"], "oc_test")
            self.assertEqual(records[0]["links"], ["https://v.douyin.com/polled/"])


if __name__ == "__main__":
    unittest.main()
