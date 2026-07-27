from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from script.frame_extractor import extract_video_frames, list_frame_files


class FrameExtractorTest(unittest.TestCase):
    def test_extract_video_frames_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "video.mp4"
            video.write_bytes(b"not-real-video")
            frames_dir = root / "frames"

            def fake_run(cmd, capture_output, text):
                self.assertIn("fps=1/2", ",".join(cmd))
                frames_dir.mkdir(parents=True, exist_ok=True)
                (frames_dir / "frame_0001.jpg").write_bytes(b"jpg")

                class Result:
                    returncode = 0
                    stderr = ""

                return Result()

            with patch("subprocess.run", side_effect=fake_run):
                manifest_path = extract_video_frames(video, frames_dir, every_seconds=2)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["every_seconds"], 2)
            self.assertEqual(manifest["frame_count"], 1)
            self.assertEqual(list_frame_files(frames_dir), [frames_dir / "frame_0001.jpg"])


if __name__ == "__main__":
    unittest.main()
