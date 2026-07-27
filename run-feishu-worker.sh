#!/usr/bin/env bash
# Process Feishu video-inbox records. Pass --dry-run to verify without downloading.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

export VIDEO_INBOX_DIR="${VIDEO_INBOX_DIR:-/Users/zhuchenyuan/AI/projects/司库/01-资料采集/Inbox/video-inbox}"
export FEISHU_APP_ID="${FEISHU_APP_ID:-cli_aaab1c2d2c785bfc}"
export FEISHU_POLL_CHAT_ID="${FEISHU_POLL_CHAT_ID:-oc_705067992099413b7560f38fe3ea6c2a}"
export FEISHU_POLL_LOOKBACK_SECONDS="${FEISHU_POLL_LOOKBACK_SECONDS:-3600}"

exec .venv/bin/python -m script.feishu_inbox_worker "$@"
