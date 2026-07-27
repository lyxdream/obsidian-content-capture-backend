#!/usr/bin/env bash
# Start Feishu long-connection listener. Requires FEISHU_APP_SECRET in env.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

export FEISHU_APP_ID="${FEISHU_APP_ID:-cli_aaab1c2d2c785bfc}"
export VIDEO_INBOX_DIR="${VIDEO_INBOX_DIR:-/Users/zhuchenyuan/AI/projects/司库/01-资料采集/Inbox/video-inbox}"

exec .venv/bin/python -m script.feishu_ws_listener "$@"
