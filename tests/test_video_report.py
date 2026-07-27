from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from script.video_report import generate_siku_reports


class VideoReportTest(unittest.TestCase):
    def test_generate_siku_reports_writes_raw_distilled_and_suggestion_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_dir = root / "output" / "123_运镜大全"
            out_dir.mkdir(parents=True)
            (out_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "aweme_id": "123",
                        "title": "4类186组运镜大全图解",
                        "author": "阿拉赛博蕾",
                        "content_type": "video",
                        "source_url": "https://v.douyin.com/test/",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (out_dir / "transcript.txt").write_text(
                "标题: 4类186组运镜大全图解\n\n--- 文案 ---\n\n"
                "这个视频整理了 Seedance 视频生成里的运镜分类、镜头节奏和提示词复用方法。"
                "提示词模板是：主体 + 动作 + 镜头运动 + 风格。"
                "在 Seedance 软件里使用 @语法 引用角色图，参数建议 motion strength 0.6。"
                "这个提示词可以简弱AI为加强人物制杆。"
                "这个提示词可以把原图片比例不变扩词。",
                encoding="utf-8",
            )
            frames_dir = out_dir / "frames"
            frames_dir.mkdir()
            (frames_dir / "frame_0001.jpg").write_bytes(b"jpg")
            (frames_dir / "frame_0002.jpg").write_bytes(b"jpg")
            (frames_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "frame_count": 2,
                        "every_seconds": 2,
                        "frames": ["frame_0001.jpg", "frame_0002.jpg"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (frames_dir / "frame_ocr.txt").write_text(
                "## frame_0001.jpg\n"
                "Seedance 提示词模板\n"
                "主体 + 动作 + 镜头运动 + 风格\n"
                "电影风格貨像\n"
                "三地角色试图\n"
                "比列不变护图\n"
                "motion strength 0.6\n"
                "## frame_0002.jpg\n"
                "人物质感提示词\n"
                "最终呈现电影级肤色带有柯达 Portra400 胶片的细腻颗粒与色彩层次。\n",
                encoding="utf-8",
            )

            reports = generate_siku_reports(
                out_dir,
                siku_root=root / "司库",
                source_link="https://v.douyin.com/test/",
                source_text="手机分享文案",
            )

            self.assertTrue(reports.knowledge_note.exists())
            self.assertTrue(reports.study_report.exists())
            self.assertTrue(reports.project_suggestion.exists())
            self.assertIn(
                "02-知识笔记/短视频爬取",
                reports.knowledge_note.as_posix(),
            )
            knowledge_text = reports.knowledge_note.read_text(encoding="utf-8")
            self.assertIn("## 初步校对内容", knowledge_text)
            self.assertIn("## 完整转写 / 配文", knowledge_text)
            self.assertIn("## 原始帧 OCR 文本", knowledge_text)
            self.assertIn("motion strength 0.6", knowledge_text)
            self.assertIn("电影风格肖像", knowledge_text)
            self.assertIn("3D角色视图", knowledge_text)
            self.assertIn("比例不变扩图", knowledge_text)
            self.assertIn("增强 AI 人物质感", knowledge_text)
            self.assertIn("电影风格貨像", knowledge_text)
            study_text = reports.study_report.read_text(encoding="utf-8")
            self.assertIn("Seedance", study_text)
            self.assertIn("## 完整转写 / 配文", study_text)
            self.assertIn("## 这条视频真正讲了什么", study_text)
            self.assertIn("不是简单复述口播", study_text)
            self.assertIn("## 视频里的可复用资产", study_text)
            self.assertIn("用途：", study_text)
            self.assertIn("## 对项目优化的建议", study_text)
            self.assertIn("## 项目 Worklist", study_text)
            self.assertIn("## 可复用资产清单", study_text)
            self.assertIn("### 提示词模板", study_text)
            self.assertIn("主体 + 动作 + 镜头运动 + 风格", study_text)
            self.assertIn("### 软件 / 工具用法", study_text)
            self.assertIn("Seedance", study_text)
            self.assertIn("### Skill / 工作流", study_text)
            self.assertIn("### 参数 / 语法", study_text)
            self.assertIn("@语法", study_text)
            self.assertIn("## 帧证据", study_text)
            self.assertIn("frame_0001.jpg", study_text)
            self.assertIn("## 帧 OCR 校对文本", study_text)
            self.assertIn("motion strength 0.6", study_text)
            self.assertIn("电影风格肖像", study_text)
            self.assertIn("3D角色视图", study_text)
            self.assertIn("比例不变扩图", study_text)
            self.assertIn("增强 AI 人物质感", study_text)
            self.assertIn("角色设定", study_text)
            self.assertIn("短视频收件箱", study_text)
            self.assertIn("增强人物皮肤真实感", study_text)
            self.assertNotIn("电影风格貨像", study_text)
            self.assertNotIn("简弱AI", study_text)
            self.assertNotIn("扩词", study_text)
            self.assertIn(
                "这个视频整理了 Seedance 视频生成里的运镜分类、镜头节奏和提示词复用方法。",
                study_text,
            )
            suggestion_text = reports.project_suggestion.read_text(encoding="utf-8")
            self.assertIn("OHHF", suggestion_text)
            self.assertIn("短视频收件箱", suggestion_text)
            self.assertIn("## 可复用资产", suggestion_text)
            self.assertIn("增强人物皮肤真实感", suggestion_text)


if __name__ == "__main__":
    unittest.main()
