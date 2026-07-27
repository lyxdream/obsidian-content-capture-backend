from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from script.audio_extractor import ensure_ffmpeg


def list_frame_files(frames_dir: Path) -> list[Path]:
    if not frames_dir.is_dir():
        return []
    return sorted(frames_dir.glob("frame_*.jpg"))


def extract_video_frames(
    video_path: Path,
    frames_dir: Path,
    *,
    every_seconds: int = 2,
    width: int = 720,
    overwrite: bool = False,
) -> Path:
    """Extract evenly sampled frames for later visual review and model analysis."""
    ensure_ffmpeg()
    frames_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = frames_dir / "manifest.json"

    if list_frame_files(frames_dir) and manifest_path.exists() and not overwrite:
        return manifest_path

    if overwrite:
        for frame in list_frame_files(frames_dir):
            frame.unlink()

    fps_expr = f"fps=1/{every_seconds}"
    scale_expr = f"scale={width}:-1"
    output_pattern = frames_dir / "frame_%04d.jpg"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"{fps_expr},{scale_expr}",
        "-q:v",
        "3",
        str(output_pattern),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 抽帧失败:\n{proc.stderr}")

    frames = list_frame_files(frames_dir)
    manifest_path.write_text(
        json.dumps(
            {
                "video": str(video_path),
                "frames_dir": str(frames_dir),
                "every_seconds": every_seconds,
                "width": width,
                "frame_count": len(frames),
                "frames": [frame.name for frame in frames],
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest_path
