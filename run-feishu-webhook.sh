#!/usr/bin/env bash
# Start the local Flask webhook receiver used by the Feishu video inbox.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

export PORT="${PORT:-5050}"
export FEISHU_EVENT_PATH_SECRET="${FEISHU_EVENT_PATH_SECRET:-inbox20260712}"
export VIDEO_INBOX_DIR="${VIDEO_INBOX_DIR:-/Users/zhuchenyuan/AI/projects/司库/01-资料采集/Inbox/video-inbox}"
export FEISHU_APP_ID="${FEISHU_APP_ID:-cli_aaab1c2d2c785bfc}"

exec .venv/bin/python web/app.py
