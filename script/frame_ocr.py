from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from script.frame_extractor import list_frame_files


class FrameOCRError(RuntimeError):
    pass


def _recognize_image_text(image_path: Path) -> list[str]:
    try:
        import Vision
        from Cocoa import NSURL
    except ImportError as e:
        raise FrameOCRError("缺少 macOS Vision OCR 依赖：pyobjc-framework-Vision") from e

    texts: list[str] = []
    url = NSURL.fileURLWithPath_(str(image_path.resolve()))
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)

    def callback(request: Any, error: Any) -> None:
        if error:
            return
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if candidates:
                text = str(candidates[0].string()).strip()
                if text:
                    texts.append(text)

    request = Vision.VNRecognizeTextRequest.alloc().initWithCompletionHandler_(callback)
    request.setRecognitionLanguages_(["zh-Hans", "en-US"])
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    handler.performRequests_error_([request], None)
    return texts


def ocr_frame_dir(
    frames_dir: Path,
    *,
    limit: int | None = None,
    overwrite: bool = False,
) -> Path:
    frames = list_frame_files(frames_dir)
    ocr_json_path = frames_dir / "frame_ocr.json"
    ocr_txt_path = frames_dir / "frame_ocr.txt"
    if ocr_json_path.exists() and ocr_txt_path.exists() and not overwrite:
        return ocr_json_path

    if limit is not None:
        frames = frames[:limit]

    records = []
    txt_lines: list[str] = []
    for frame in frames:
        texts = _recognize_image_text(frame)
        records.append({"frame": frame.name, "texts": texts})
        if texts:
            txt_lines.append(f"## {frame.name}")
            txt_lines.extend(texts)
            txt_lines.append("")

    payload = {
        "frames_dir": str(frames_dir),
        "frame_count": len(frames),
        "ocr_frame_count": len(records),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "records": records,
    }
    ocr_json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    ocr_txt_path.write_text("\n".join(txt_lines).strip() + "\n", encoding="utf-8")
    return ocr_json_path


def read_frame_ocr_text(out_dir: Path) -> str:
    path = out_dir / "frames" / "frame_ocr.txt"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()
