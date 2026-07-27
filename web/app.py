#!/usr/bin/env python3
"""Web 入口：浏览器内输入抖音链接并提取文案。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import unquote

_ROOT = Path(__file__).resolve().parent.parent


def _reexec_with_venv_if_needed() -> None:
    try:
        import flask  # noqa: F401
    except ImportError:
        venv_python = _ROOT / ".venv" / "bin" / "python"
        if venv_python.is_file():
            os.execv(
                str(venv_python),
                [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]],
            )
        print(
            "缺少依赖。请先执行：\n"
            "  source .venv/bin/activate && pip install -r requirements.txt\n"
            "或运行：./run-web.sh",
            file=sys.stderr,
        )
        raise SystemExit(1)


_reexec_with_venv_if_needed()

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import requests
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    make_response,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from script.config import Settings
from script.douyin_resolver import resolve_douyin_share
from script.feishu_inbox import (
    append_feishu_inbox,
    extract_douyin_links,
    extract_message_text,
)
from script.feishu_reply import queued_reply_text, try_send_reply
from script.paths import OUTPUT_DIR
from script.pipeline import process_douyin_share

app = Flask(__name__, template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]


def _read_transcript(out_dir: Path) -> str:
    path = out_dir / "transcript.txt"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    marker = "--- 文案 ---"
    if marker in text:
        return text.split(marker, 1)[1].strip()
    return text.strip()


def _list_images(out_dir: Path) -> list[str]:
    images_dir = out_dir / "images"
    if not images_dir.is_dir():
        return []
    rel = out_dir.relative_to(OUTPUT_DIR)
    files = sorted(images_dir.glob("*"))
    return [
        url_for("serve_output", subpath=f"{rel.as_posix()}/images/{f.name}")
        for f in files
        if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    ]


def _meta_payload(meta) -> dict:
    return {
        "success": True,
        "video_id": meta.aweme_id,
        "aweme_id": meta.aweme_id,
        "title": meta.title,
        "author": meta.author,
        "content_type": meta.content_type,
        "aweme_type": meta.aweme_type,
        "download_url": meta.download_url,
        "cover_url": meta.cover_url,
        "image_urls": meta.image_urls,
        "image_count": len(meta.image_urls),
        "source_url": meta.source_url,
    }


def _render_index_page(*, result=None, error=None):
    return render_template(
        "index.html",
        models=WHISPER_MODELS,
        default_model="small",
        result=result,
        error=error,
    )


@app.route("/api/feishu/events", defaults={"path_secret": ""}, methods=["POST"])
@app.route("/api/feishu/events/<path_secret>", methods=["POST"])
def api_feishu_events(path_secret: str):
    """Receive Feishu event callbacks and queue Douyin links for later processing."""
    expected_secret = os.environ.get("FEISHU_EVENT_PATH_SECRET", "").strip()
    if expected_secret and path_secret != expected_secret:
        return jsonify({"success": False, "error": "invalid callback path"}), 404

    payload = request.get_json(silent=True) or {}

    expected_token = os.environ.get("FEISHU_VERIFICATION_TOKEN", "").strip()
    incoming_token = payload.get("token") or (payload.get("header") or {}).get("token")
    if expected_token and incoming_token != expected_token:
        return jsonify({"success": False, "error": "invalid token"}), 403

    challenge = payload.get("challenge")
    if challenge:
        return jsonify({"challenge": challenge})

    event = payload.get("event") or {}
    text = extract_message_text(event)
    links = extract_douyin_links(text)
    if not links:
        return jsonify({"success": True, "queued": 0, "message": "no douyin link"})

    inbox_path, record = append_feishu_inbox(payload, links=links, text=text)
    reply_error = try_send_reply(
        record.get("message_id"),
        queued_reply_text(link_count=len(links)),
    )
    response = {"success": True, "queued": len(links), "inbox": str(inbox_path)}
    if reply_error:
        response["reply_error"] = reply_error
    return jsonify(response)


@app.route("/", methods=["GET", "POST"])
def index():
    """GET 渲染 SPA；POST 兼容旧版表单或缓存页面提交到 / 的情况。"""
    if request.method == "GET":
        resp = make_response(_render_index_page())
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp

    # 旧表单字段 share_text / model
    share_text = (request.form.get("share_text") or request.form.get("url") or "").strip()
    if not share_text and request.is_json:
        data = request.get_json(silent=True) or {}
        share_text = (data.get("url") or data.get("share_text") or "").strip()

    if not share_text:
        return _render_index_page(error="请输入抖音分享链接或分享文案"), 400

    model = request.form.get("model") or "small"
    if model not in WHISPER_MODELS:
        model = "small"

    try:
        out_dir = process_douyin_share(
            share_text,
            settings=Settings(output_dir=OUTPUT_DIR, whisper_model=model),
        )
        meta_path = out_dir / "meta.json"
        meta = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        rel = out_dir.relative_to(OUTPUT_DIR).as_posix()
        result = {
            "content_type": meta.get("content_type", "video"),
            "aweme_id": meta.get("aweme_id", ""),
            "title": meta.get("title", ""),
            "author": meta.get("author", ""),
            "out_dir": str(out_dir.resolve()),
            "rel_dir": rel,
            "transcript": _read_transcript(out_dir),
            "images": _list_images(out_dir),
        }
        return _render_index_page(result=result)
    except Exception as e:
        return _render_index_page(error=str(e)), 500


@app.route("/api/health")
def api_health():
    """本地 Whisper 模式，无需云端 API Key。"""
    return jsonify(
        {
            "success": True,
            "api_key_configured": True,
            "engine": "local",
            "whisper": "faster-whisper",
            "models": WHISPER_MODELS,
        }
    )


@app.route("/api/video/info", methods=["POST"])
def api_video_info():
    data = request.get_json(silent=True) or {}
    share_text = (data.get("url") or "").strip()
    if not share_text:
        return jsonify({"success": False, "error": "请输入分享链接"}), 400
    try:
        meta = resolve_douyin_share(share_text)
        return jsonify(_meta_payload(meta))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/video/extract", methods=["POST"])
def api_video_extract():
    data = request.get_json(silent=True) or {}
    share_text = (data.get("url") or "").strip()
    model = data.get("model") or "small"
    if model not in WHISPER_MODELS:
        model = "small"
    skip_transcribe = bool(
        data.get("skip_transcribe") or data.get("mode") == "video_only"
    )
    if not share_text:
        return jsonify({"success": False, "error": "请输入分享链接"}), 400
    try:
        out_dir = process_douyin_share(
            share_text,
            settings=Settings(
                output_dir=OUTPUT_DIR,
                whisper_model=model,
                skip_transcribe=skip_transcribe,
            ),
        )
        meta_path = out_dir / "meta.json"
        meta = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))

        video_dl = ""
        if meta.get("content_type") == "video":
            dl_path = out_dir / "download_url.txt"
            if dl_path.exists():
                video_dl = dl_path.read_text(encoding="utf-8").strip()
            elif meta.get("download_url"):
                video_dl = meta["download_url"]

        return jsonify(
            {
                "success": True,
                "video_id": meta.get("aweme_id", ""),
                "title": meta.get("title", ""),
                "author": meta.get("author", ""),
                "content_type": meta.get("content_type", "video"),
                "download_url": video_dl,
                "text": _read_transcript(out_dir),
                "out_dir": str(out_dir.resolve()),
                "images": _list_images(out_dir),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/video/download")
def api_video_download():
    """代理下载无水印视频直链。"""
    raw_url = request.args.get("url", "")
    filename = request.args.get("filename", "video.mp4")
    if not raw_url:
        abort(400)
    safe_name = Path(filename).name
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15"
        ),
        "Referer": "https://www.iesdouyin.com/",
    }
    upstream = requests.get(raw_url, headers=headers, stream=True, timeout=120)
    upstream.raise_for_status()

    def generate():
        for chunk in upstream.iter_content(chunk_size=1024 * 256):
            if chunk:
                yield chunk

    resp = Response(generate(), content_type="video/mp4")
    resp.headers["Content-Disposition"] = f'attachment; filename="{safe_name}"'
    return resp


@app.route("/files/<path:subpath>")
def serve_output(subpath: str):
    """预览已下载的图片、视频等资源。"""
    subpath = unquote(subpath)
    target = (OUTPUT_DIR / subpath).resolve()
    root = OUTPUT_DIR.resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        abort(404)
    return send_from_directory(target.parent, target.name)


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    port = int(os.environ.get("PORT", "5050"))
    debug = os.environ.get("FLASK_DEBUG", "").strip() == "1"
    print(f"打开浏览器访问: http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=debug)
