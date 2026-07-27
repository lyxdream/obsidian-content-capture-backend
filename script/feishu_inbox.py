from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from script.config import Settings
from script.feishu_reply import ReplySender, processed_reply_text, try_send_reply
from script.paths import OUTPUT_DIR

DOUYIN_LINK_RE = re.compile(
    r"https?://(?:v\.douyin\.com|www\.douyin\.com|www\.iesdouyin\.com|m\.douyin\.com)[^\s\]）)\"'<>]*"
)


@dataclass(frozen=True)
class InboxProcessSummary:
    scanned_records: int = 0
    skipped_results: int = 0
    created_results: int = 0
    failed_results: int = 0
    reply_sent: int = 0
    reply_failed: int = 0


def default_inbox_dir() -> Path:
    return Path(os.environ.get("VIDEO_INBOX_DIR", str(OUTPUT_DIR / "_inbox")))


def default_inbox_files(inbox_dir: Path | None = None) -> tuple[Path, Path]:
    root = inbox_dir or default_inbox_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root / "feishu-events.jsonl", root / "processed-events.jsonl"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def extract_message_text(event: dict[str, Any]) -> str:
    message = event.get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, str):
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return content.strip()
    elif isinstance(content, dict):
        payload = content
    else:
        return ""
    return str(payload.get("text") or payload.get("content") or "").strip()


def extract_douyin_links(text: str) -> list[str]:
    seen: set[str] = set()
    links: list[str] = []
    for raw in DOUYIN_LINK_RE.findall(text):
        link = raw.rstrip("。,.，、:：;；!！?？")
        if link and link not in seen:
            seen.add(link)
            links.append(link)
    return links


def build_feishu_record(
    payload: dict[str, Any],
    *,
    text: str | None = None,
    links: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    event = payload.get("event") or {}
    message = event.get("message") or {}
    message_text = extract_message_text(event) if text is None else text
    douyin_links = extract_douyin_links(message_text) if links is None else links
    received_at = now or datetime.now(timezone.utc)
    return {
        "source": "feishu",
        "status": "queued",
        "links": douyin_links,
        "text": message_text,
        "event_type": (payload.get("header") or {}).get("event_type") or payload.get("type"),
        "message_id": message.get("message_id"),
        "chat_id": message.get("chat_id"),
        "received_at": received_at.isoformat(),
    }


def append_feishu_inbox(
    payload: dict[str, Any],
    *,
    inbox_dir: Path | None = None,
    text: str | None = None,
    links: list[str] | None = None,
    now: datetime | None = None,
) -> tuple[Path, dict[str, Any]]:
    inbox_path, _ = default_inbox_files(inbox_dir)
    record = build_feishu_record(payload, text=text, links=links, now=now)
    append_jsonl(inbox_path, record)
    return inbox_path, record


def _record_identity(record: dict[str, Any]) -> str:
    message_id = record.get("message_id")
    if message_id:
        return str(message_id)
    raw = json.dumps(
        {"text": record.get("text", ""), "links": record.get("links", [])},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _result_key(record: dict[str, Any], link: str) -> str:
    return f"{_record_identity(record)}::{link}"


def _completed_keys(processed_path: Path, *, include_dry_run: bool) -> set[str]:
    statuses = {"processed"}
    if include_dry_run:
        statuses.add("dry_run")
    keys: set[str] = set()
    for item in read_jsonl(processed_path):
        if item.get("status") not in statuses:
            continue
        source_id = item.get("source_record_id") or item.get("message_id") or ""
        link = item.get("link") or ""
        if source_id and link:
            keys.add(f"{source_id}::{link}")
        if link:
            keys.add(f"link::{link}")
    return keys


def process_inbox_once(
    inbox_path: Path | None = None,
    processed_path: Path | None = None,
    *,
    output_dir: Path = OUTPUT_DIR,
    model: str = "small",
    device: str = "auto",
    compute_type: str = "default",
    skip_transcribe: bool = False,
    dry_run: bool = False,
    write_reports: bool = True,
    siku_root: Path | None = None,
    gbrain_capture: bool = False,
    gbrain_source: str = "default",
    limit: int | None = None,
    reply_sender: ReplySender | None = None,
) -> InboxProcessSummary:
    default_inbox_path, default_processed_path = default_inbox_files()
    source_path = inbox_path or default_inbox_path
    result_path = processed_path or default_processed_path
    completed = _completed_keys(result_path, include_dry_run=dry_run)

    scanned = 0
    skipped = 0
    created = 0
    failed = 0
    reply_sent = 0
    reply_failed = 0

    for record in read_jsonl(source_path):
        if record.get("status") != "queued":
            continue
        scanned += 1
        for link in record.get("links") or []:
            if limit is not None and created >= limit:
                return InboxProcessSummary(scanned, skipped, created, failed, reply_sent, reply_failed)

            source_id = _record_identity(record)
            key = _result_key(record, link)
            if key in completed or f"link::{link}" in completed:
                skipped += 1
                continue

            result = {
                "source": "feishu",
                "source_record_id": source_id,
                "message_id": record.get("message_id"),
                "link": link,
                "text": record.get("text", ""),
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }
            if dry_run:
                result["status"] = "dry_run"
            else:
                try:
                    from script.pipeline import process_douyin_share

                    out_dir = process_douyin_share(
                        link,
                        settings=Settings(
                            output_dir=output_dir,
                            whisper_model=model,
                            whisper_device=device,
                            whisper_compute_type=compute_type,
                            skip_transcribe=skip_transcribe,
                        ),
                    )
                    result["status"] = "processed"
                    result["out_dir"] = str(out_dir.resolve())
                    if write_reports:
                        from script.video_report import DEFAULT_SIKU_ROOT, generate_siku_reports

                        reports = generate_siku_reports(
                            out_dir,
                            siku_root=siku_root or DEFAULT_SIKU_ROOT,
                            source_link=link,
                            source_text=str(record.get("text", "")),
                        )
                        result["knowledge_note"] = str(reports.knowledge_note)
                        result["study_report"] = str(reports.study_report)
                        result["project_suggestion"] = str(reports.project_suggestion)

                        if gbrain_capture:
                            import subprocess

                            capture = subprocess.run(
                                [
                                    "gbrain",
                                    "capture",
                                    "--file",
                                    str(reports.study_report),
                                    "--source",
                                    gbrain_source,
                                    "--quiet",
                                ],
                                check=False,
                                capture_output=True,
                                text=True,
                            )
                            if capture.returncode == 0:
                                result["gbrain_slug"] = capture.stdout.strip()
                            else:
                                result["gbrain_error"] = (capture.stderr or capture.stdout).strip()
                except Exception as e:  # pragma: no cover - depends on network/platform
                    failed += 1
                    result["status"] = "failed"
                    result["error"] = str(e)

            reply_error = try_send_reply(
                record.get("message_id"),
                processed_reply_text(result),
                reply_sender=reply_sender,
            )
            if reply_error:
                result["reply_error"] = reply_error
                reply_failed += 1
            else:
                reply_sent += 1

            append_jsonl(result_path, result)
            completed.add(key)
            completed.add(f"link::{link}")
            created += 1

    return InboxProcessSummary(scanned, skipped, created, failed, reply_sent, reply_failed)
