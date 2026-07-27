from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from script.frame_ocr import read_frame_ocr_text


DEFAULT_SIKU_ROOT = Path("/Users/zhuchenyuan/AI/projects/司库")

COMMON_TEXT_CORRECTIONS = {
    "简弱AI为加强人物制杆": "增强 AI 人物质感",
    "简弱 AI 为加强人物制杆": "增强 AI 人物质感",
    "简弱AI为加强人物质感": "增强 AI 人物质感",
    "简弱 AI 为加强人物质感": "增强 AI 人物质感",
    "移出初骗的视频人数": "移除图片的饰品元素",
    "移出图片的视频人数": "移除图片的饰品元素",
    "移出初骗的饰品元素": "移除图片的饰品元素",
    "特显销项": "特写肖像",
    "電影风格貨像": "电影风格肖像",
    "电影风格貨像": "电影风格肖像",
    "電影风格肖像": "电影风格肖像",
    "貨像": "肖像",
    "比列不变护图": "比例不变扩图",
    "比例不变扩词": "比例不变扩图",
    "比列": "比例",
    "护图": "扩图",
    "扩词": "扩图",
    "老照顺": "老照片",
    "平分系统": "评分系统",
    "三地角色试图": "3D角色视图",
    "三地角色視图": "3D角色视图",
    "三地": "3D",
    "彻图": "视图",
    "制杆": "质感",
    "初骗": "图片",
    "视频人数": "饰品元素",
    "豆绘Al": "豆绘AI",
    "A饅": "AI帮",
    " Al ": " AI ",
    "Al为": "AI为",
    "Al人物": "AI人物",
}


@dataclass(frozen=True)
class SikuReportPaths:
    knowledge_note: Path
    study_report: Path
    project_suggestion: Path


@dataclass(frozen=True)
class VideoAsset:
    title: str
    purpose: str
    key_points: list[str]
    source_frames: list[str]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_transcript(out_dir: Path) -> str:
    path = out_dir / "transcript.txt"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    marker = "--- 文案 ---"
    if marker in text:
        return text.split(marker, 1)[1].strip()
    return text


def _read_frame_manifest(out_dir: Path) -> dict[str, Any]:
    manifest_path = out_dir / "frames" / "manifest.json"
    if not manifest_path.exists():
        return {}
    return _read_json(manifest_path)


def _safe_filename(value: str, *, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|#\[\]\n\r\t]+", "-", value).strip(" .-")
    text = re.sub(r"\s+", "", text)
    return (text or fallback)[:48]


def _clean_recognized_text(text: str) -> str:
    cleaned = text
    for source, target in COMMON_TEXT_CORRECTIONS.items():
        cleaned = cleaned.replace(source, target)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _frontmatter(**items: str) -> str:
    lines = ["---"]
    for key, value in items.items():
        escaped = str(value).replace('"', '\\"')
        lines.append(f'{key}: "{escaped}"')
    lines.append("---")
    return "\n".join(lines)


def _extract_points(text: str, *, limit: int = 8) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ["原始内容暂未提取到足够文本，需要回看视频或重新转写。"]
    parts = re.split(r"[。！？!?；;]\s*", cleaned)
    points = [p.strip(" ，,") for p in parts if len(p.strip()) >= 8]
    if not points:
        return [cleaned[:180]]
    return points[:limit]


def _sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    parts = re.split(r"(?<=[。！？!?；;])\s*|\n+", cleaned)
    return [part.strip(" ，,。") for part in parts if part.strip(" ，,。")]


def _matching_sentences(text: str, keywords: list[str], *, limit: int = 10) -> list[str]:
    matches: list[str] = []
    for sentence in _sentences(text):
        lower = sentence.lower()
        if any(keyword.lower() in lower for keyword in keywords):
            matches.append(sentence)
    return matches[:limit] or ["未从转写中明确提取到，需结合视频画面复核。"]


def _full_content_block(transcript: str) -> str:
    if not transcript.strip():
        return "暂未提取到正文。"
    return transcript.strip()


def _asset_sections(text: str, title: str) -> dict[str, list[str]]:
    corpus = f"{title}\n{text}"
    return {
        "提示词模板": _matching_sentences(
            corpus,
            ["提示词", "prompt", "模板", "主体", "风格", "镜头", "运镜", "角色"],
        ),
        "软件 / 工具用法": _matching_sentences(
            corpus,
            ["软件", "工具", "seedance", "comfyui", "豆绘", "剪映", "使用", "打开", "导入"],
        ),
        "Skill / 工作流": _matching_sentences(
            corpus,
            ["skill", "工作流", "流程", "步骤", "先", "然后", "最后", "拆解", "复用"],
        ),
        "参数 / 语法": _matching_sentences(
            corpus,
            ["参数", "语法", "@", "strength", "ratio", "seed", "fps", "motion", "权重"],
        ),
    }


def _asset_section_markdown(sections: dict[str, list[str]]) -> str:
    chunks: list[str] = []
    for title, items in sections.items():
        chunks.append(f"### {title}")
        chunks.append(_bullet_list(items))
    return "\n\n".join(chunks)


def _frame_blocks(frame_ocr_text: str) -> list[tuple[str, list[str]]]:
    blocks: list[tuple[str, list[str]]] = []
    current_frame = ""
    current_lines: list[str] = []
    for raw_line in frame_ocr_text.splitlines():
        line = raw_line.strip()
        match = re.match(r"^##\s+(.+)$", line)
        if match:
            if current_frame:
                blocks.append((current_frame, current_lines))
            current_frame = match.group(1).strip()
            current_lines = []
            continue
        if current_frame:
            current_lines.append(line)
    if current_frame:
        blocks.append((current_frame, current_lines))
    return blocks


def _compact_line(line: str) -> str:
    return re.sub(r"\s+", "", line).strip(" ，,。；;")


def _asset_purpose(title: str, text: str) -> str:
    title_lower = title.lower()
    title_rules = [
        (["3d", "三视图", "角色视图", "角色"], "把人物生成角色设定板，用于 OHHF 的角色一致性、分镜和视觉资产生产。"),
        (["电影", "肖像"], "把普通人物照转成电影感特写肖像，强调光线、景深、胶片颗粒和真实皮肤细节。"),
        (["老照片", "修复"], "把旧照片修复成更清晰、色彩更现代的专业肖像，同时保留准确面部特征。"),
        (["评分", "面部特征"], "生成面部特征分析或评分界面，适合角色审美分析和虚拟人物对比。"),
        (["扩图", "比例不变"], "在不破坏人物比例、身份和原构图逻辑的前提下扩展画面。"),
        (["移除", "饰品", "去除"], "移除人物图片里的饰品或局部元素，同时尽量保持人物身份、姿态、服装和光影。"),
        (["质感", "皮肤", "毛孔"], "增强人物皮肤真实感，修正 AI 人像常见的塑料感、蜡像感和过度磨皮。"),
    ]
    for keywords, purpose in title_rules:
        if any(keyword in title_lower for keyword in keywords):
            return purpose

    haystack = f"{title}\n{text}".lower()
    rules = [
        (["3d", "三视图", "角色视图", "角色"], "把人物生成角色设定板，用于 OHHF 的角色一致性、分镜和视觉资产生产。"),
        (["电影", "肖像", "浅景深"], "把普通人物照转成电影感特写肖像，强调光线、景深、胶片颗粒和真实皮肤细节。"),
        (["老照片", "修复", "dslr"], "把旧照片修复成更清晰、色彩更现代的专业肖像，同时保留准确面部特征。"),
        (["评分", "面部特征"], "生成面部特征分析或评分界面，适合角色审美分析和虚拟人物对比。"),
        (["扩图", "比例不变"], "在不破坏人物比例、身份和原构图逻辑的前提下扩展画面。"),
        (["移除", "饰品", "去除"], "移除人物图片里的饰品或局部元素，同时尽量保持人物身份、姿态、服装和光影。"),
        (["seedance", "运镜", "镜头"], "沉淀视频生成的镜头、运镜、参数或提示词模板，方便后续复用。"),
        (["豆绘", "工具", "万能改图"], "说明视频使用的 AI 图像工具入口和能力边界。"),
        (["质感", "皮肤", "毛孔"], "增强人物皮肤真实感，修正 AI 人像常见的塑料感、蜡像感和过度磨皮。"),
    ]
    for keywords, purpose in rules:
        if any(keyword in haystack for keyword in keywords):
            return purpose
    return "从视频画面中抽取出的可复用知识点，需要结合原视频复核后再沉淀为模板。"


def _asset_title_from_lines(lines: list[str], fallback: str) -> str:
    for line in lines:
        compact = _compact_line(line)
        if not compact:
            continue
        if compact in {"这个提示词", "可以", "这个工具"}:
            continue
        return compact[:36]
    return fallback


def _asset_key_points(lines: list[str], *, title: str, limit: int = 8) -> list[str]:
    cleaned_lines: list[str] = []
    title_compact = _compact_line(title)
    skip_values = {"这个提示词", "这个工具", "可以"}
    for line in lines:
        compact = _compact_line(line)
        if not compact or compact in skip_values or compact == title_compact:
            continue
        if len(compact) < 3:
            continue
        cleaned_lines.append(compact)
    points = _merge_ocr_lines(cleaned_lines, limit=limit)
    if not points:
        return ["该帧只展示了结论或成品，需要结合前后帧复核完整提示词。"]
    return points


def _merge_ocr_lines(lines: list[str], *, limit: int) -> list[str]:
    merged: list[str] = []
    current = ""
    for line in lines:
        if not current:
            current = line
        else:
            current += line
        if re.search(r"[。！？!?；;：:]$", line) or len(current) >= 70:
            merged.append(current.strip(" ，,"))
            current = ""
        if len(merged) >= limit:
            break
    if current and len(merged) < limit:
        merged.append(current.strip(" ，,"))
    return merged[:limit]


def _extract_video_assets(frame_ocr_text: str, transcript: str, title: str) -> list[VideoAsset]:
    assets: list[VideoAsset] = []
    seen: set[str] = set()
    for frame_name, lines in _frame_blocks(frame_ocr_text):
        block_text = "\n".join(lines)
        asset_title = _asset_title_from_lines(lines, fallback=frame_name)
        haystack = f"{asset_title}\n{block_text}"
        if not any(
            keyword in haystack
            for keyword in ["提示词", "模板", "肖像", "质感", "扩图", "修复", "评分", "角色", "运镜", "工具", "豆绘", "Seedance"]
        ):
            continue
        normalized_title = _compact_line(asset_title)
        if normalized_title in seen:
            continue
        seen.add(normalized_title)
        assets.append(
            VideoAsset(
                title=asset_title,
                purpose=_asset_purpose(asset_title, block_text),
                key_points=_asset_key_points(lines, title=asset_title),
                source_frames=[frame_name],
            )
        )
    if assets:
        return assets[:12]

    fallback_points = _extract_points(transcript, limit=6)
    return [
        VideoAsset(
            title=title,
            purpose="从口播和配文中抽取出的核心内容，需要结合原视频复核视觉细节。",
            key_points=fallback_points,
            source_frames=[],
        )
    ]


def _video_understanding(text: str, title: str, assets: list[VideoAsset]) -> str:
    haystack = f"{title}\n{text}"
    asset_names = "、".join(asset.title for asset in assets[:7])
    if any(keyword in haystack for keyword in ["提示词", "肖像", "质感", "扩图", "3D角色", "豆绘"]):
        return (
            "这条视频不是简单复述口播，而是在展示一组可复用的视觉提示词资产。"
            "核心是把人物图像任务拆成“目标 + 保留约束 + 视觉细节 + 输出格式”："
            f"视频里的主要资产包括 {asset_names}。"
            "这些内容的价值不只是某个工具本身，而是可以迁移到 OHHF、司库和 gbrain 的提示词方法库。"
        )
    if any(keyword.lower() in haystack.lower() for keyword in ["seedance", "运镜", "镜头", "motion"]):
        return (
            "这条视频不是简单复述口播，而是在整理视频生成里的镜头和运镜方法。"
            f"可复用资产包括 {asset_names}，适合沉淀为视频生成提示词模板和 OHHF 镜头语言检查项。"
        )
    if any(keyword in haystack for keyword in ["量化", "交易", "止损", "股票"]):
        return (
            "这条视频不是简单复述口播，而是在提出一个交易或市场机制观点。"
            f"当前可抽取的证据包括 {asset_names}，应先作为研究假设进入验证，不直接变成交易信号。"
        )
    return (
        "这条视频不是简单复述口播，而是提供了一组可复用知识点。"
        f"当前识别出的主要资产包括 {asset_names}，需要结合项目场景再判断落地价值。"
    )


def _video_asset_markdown(assets: list[VideoAsset]) -> str:
    chunks: list[str] = []
    for index, asset in enumerate(assets, start=1):
        section = [
            f"### {index}. {asset.title}",
            f"用途：{asset.purpose}",
            "",
            "关键内容：",
            _bullet_list(asset.key_points),
        ]
        if asset.source_frames:
            section.extend(["", f"来源帧：{', '.join(asset.source_frames)}"])
        chunks.append("\n".join(section))
    return "\n\n".join(chunks)


def _standard_summary(text: str, assets: list[VideoAsset]) -> str:
    if any("角色" in asset.title or "3D" in asset.title for asset in assets) or "3D角色" in text:
        return (
            "这条视频最值得沉淀的是“人物视觉资产生成”的提示词拆法：先明确任务类型，"
            "再写清需要保留的人物身份、面部特征、姿态、服装、比例和光影，"
            "最后规定输出形态，例如电影肖像、比例不变扩图、老照片修复或角色设定板。"
        )
    return (
        "这条视频的价值在于把零散经验转成可复用资产。后续处理时，不应只保存转写文本，"
        "而要抽取任务类型、关键步骤、可复用模板、适用项目和验证方式。"
    )


def _project_optimization_markdown(projects: list[str], text: str, assets: list[VideoAsset]) -> str:
    sections: list[str] = []
    visual_related = any(
        keyword in text for keyword in ["提示词", "肖像", "质感", "扩图", "角色", "运镜", "Seedance", "豆绘"]
    )
    if "OHHF" in projects or visual_related:
        sections.extend(
            [
                "### OHHF",
                "- 把本视频拆成视觉提示词模板，而不是只作为参考链接保存。",
                "- 优先沉淀角色设定、人物质感、电影肖像、扩图、修复等模块。",
                "- 对角色类内容增加一致性 QA：脸型、发型、服装、配饰、色卡、身高比例和三视图是否稳定。",
            ]
        )
    sections.extend(
        [
            "### obsidian-backend / 短视频收件箱",
            "- 新增“视频理解层”：先判断帧类型，再抽取提示词页、成品页、工具页和项目建议。",
            "- 对提示词页输出资产卡：标题、用途、关键内容、来源帧、适用项目和复核点。",
            "- 报告主文使用理解后的资产卡，原始 OCR 和转写只放在证据区。",
            "### 司库",
            "- 将高价值视频沉淀到方法库，而不是停留在单条视频笔记。",
            "- 建议按主题建立长期文件，例如视觉提示词、视频生成运镜、交易研究假设等。",
            "### gbrain",
            "- 入库时拆成可检索知识键，而不是只 capture 整篇视频报告。",
            "- 示例：visual.prompt.person.skin_texture、visual.prompt.character_sheet.three_view、video.workflow.camera_motion。",
        ]
    )
    if "恭喜发财" in projects:
        sections.extend(
            [
                "### 恭喜发财",
                "- 只把视频观点作为研究假设或风险提示，先验证数据和边界条件，不直接写入交易规则。",
            ]
        )
    return "\n".join(sections)


def _standard_worklist(projects: list[str], text: str) -> list[str]:
    items = [
        "把这条视频拆成资产卡，并检查每张卡是否包含用途、关键内容、来源帧和复核点。",
        "把高价值资产沉淀到司库方法库，而不是只保存在单条视频报告里。",
        "对报告执行 gbrain capture 前，补充可检索标签或知识键。",
    ]
    if "OHHF" in projects or any(keyword in text for keyword in ["提示词", "肖像", "角色", "运镜", "Seedance"]):
        items.insert(0, "把视觉提示词资产转成 OHHF 可复用模板，并选一个小样验证。")
    if "恭喜发财" in projects:
        items.insert(0, "把视频观点转成研究假设，先验证数据和反例，不进入交易执行层。")
    return [f"[ ] {item}" for item in items]


def _frame_evidence_markdown(out_dir: Path) -> str:
    manifest = _read_frame_manifest(out_dir)
    frames = manifest.get("frames") or []
    if not frames:
        return "暂未抽取视频帧。"
    every = manifest.get("every_seconds", "未知")
    lines = [
        f"- 帧目录：`{out_dir / 'frames'}`",
        f"- 抽帧间隔：每 {every} 秒",
        f"- 帧数量：{manifest.get('frame_count', len(frames))}",
        "- 帧索引：",
    ]
    lines.extend(f"  - `{name}`" for name in frames[:120])
    if len(frames) > 120:
        lines.append(f"  - 其余 {len(frames) - 120} 帧见本地目录。")
    return "\n".join(lines)


def _infer_projects(text: str, title: str) -> list[str]:
    haystack = f"{title}\n{text}".lower()
    projects: list[str] = []
    rules = [
        ("OHHF", ["seedance", "comfyui", "运镜", "镜头", "视频生成", "aicg", "图像", "视觉"]),
        ("gbrain", ["知识库", "rag", "记忆", "语义", "检索", "知识图谱", "agent"]),
        ("司库", ["obsidian", "笔记", "知识管理", "流程", "归档", "资料"]),
        ("恭喜发财", ["量化", "股票", "交易", "因子", "回测", "投资", "a股"]),
        ("Horizon", ["自动化", "调度", "日报", "飞书", "webhook", "系统"]),
    ]
    for project, keywords in rules:
        if any(keyword.lower() in haystack for keyword in keywords):
            projects.append(project)
    return projects or ["待人工归类"]


def _bullet_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _project_actions(projects: list[str]) -> list[str]:
    actions = ["将本视频先作为参考资料保留，不自动改动任何项目代码。"]
    if "OHHF" in projects:
        actions.append("评估是否能转成运镜/镜头语言提示词模板或 ComfyUI 工作流检查项。")
    if "恭喜发财" in projects:
        actions.append("提炼为研究假设或风险提示，先进入研究层验证，不直接进入交易信号。")
    if "gbrain" in projects:
        actions.append("评估是否能变成记忆检索、语义路由或证据组织规则。")
    if "司库" in projects:
        actions.append("评估是否能变成知识采集、标签路由或报告模板。")
    if "Horizon" in projects:
        actions.append("评估是否能变成自动化调度、通知或运行观测规则。")
    if projects == ["待人工归类"]:
        actions.append("先人工判断归属项目，再决定是否进入项目 Worklist。")
    return actions


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return path


def generate_siku_reports(
    out_dir: Path,
    *,
    siku_root: Path = DEFAULT_SIKU_ROOT,
    source_link: str = "",
    source_text: str = "",
    now: datetime | None = None,
) -> SikuReportPaths:
    meta = _read_json(out_dir / "meta.json")
    transcript = _read_transcript(out_dir)
    frame_ocr_text = read_frame_ocr_text(out_dir)
    clean_transcript = _clean_recognized_text(transcript)
    clean_frame_ocr_text = _clean_recognized_text(frame_ocr_text)
    clean_source_text = _clean_recognized_text(source_text)
    analysis_text = "\n".join(
        part for part in [clean_transcript, clean_frame_ocr_text, clean_source_text] if part
    )
    created_at = now or datetime.now().astimezone()
    date = created_at.strftime("%Y-%m-%d")
    aweme_id = str(meta.get("aweme_id") or meta.get("video_id") or out_dir.name)
    title = str(meta.get("title") or "未命名短视频")
    author = str(meta.get("author") or "未知作者")
    content_type = str(meta.get("content_type") or "unknown")
    source_url = source_link or str(meta.get("source_url") or "")
    filename = f"{date}__Douyin__{_safe_filename(title, fallback=aweme_id)}.md"

    points = _extract_points(analysis_text)
    projects = _infer_projects(analysis_text, title)
    assets = _asset_sections(analysis_text, title)
    video_assets = _extract_video_assets(clean_frame_ocr_text, clean_transcript, title)
    understanding = _video_understanding(analysis_text, title, video_assets)
    standard_summary = _standard_summary(analysis_text, video_assets)
    project_optimization = _project_optimization_markdown(projects, analysis_text, video_assets)
    standard_worklist = _standard_worklist(projects, analysis_text)
    frame_evidence = _frame_evidence_markdown(out_dir)

    knowledge_note = siku_root / "02-知识笔记" / "短视频爬取" / filename
    study_report = siku_root / "03-知识加工" / "蒸馏精华" / "短视频学习" / filename
    project_suggestion = siku_root / "03-知识加工" / "智能建议" / "项目优化建议" / filename

    common_fm = {
        "type": "douyin-video-capture",
        "source": "feishu-mage",
        "date": date,
        "aweme_id": aweme_id,
        "title": title,
        "author": author,
        "source_url": source_url,
    }

    knowledge_content = f"""{_frontmatter(**{**common_fm, "type": "douyin-full-crawl-note"})}
# 短视频完整爬取：{title}

## 基本信息
- 作者：{author}
- 类型：{content_type}
- 抖音链接：{source_url or "未记录"}
- 本地素材目录：{out_dir}

## 手机分享原文
{source_text or "未记录"}

## 帧证据
{frame_evidence}

## 初步校对内容
说明：本节对 ASR / OCR 常见错词做了机器校对，仍需结合下方原始证据复核关键提示词、参数和界面文字。

### 帧 OCR 校对文本
{clean_frame_ocr_text or "暂未识别到帧中文字。"}

### 转写 / 配文校对文本
{_full_content_block(clean_transcript)}

## 原始帧 OCR 文本
{frame_ocr_text or "暂未识别到帧中文字。"}

## 完整转写 / 配文（原始）
{_full_content_block(transcript)}
"""

    study_content = f"""{_frontmatter(**{**common_fm, "type": "douyin-study-report"})}
# 短视频学习报告：{title}

## 这条视频真正讲了什么
{understanding}

## 视频里的可复用资产
{_video_asset_markdown(video_assets)}

## 总结
{standard_summary}

## 对项目优化的建议
{project_optimization}

## 项目 Worklist
{_bullet_list(standard_worklist)}

## 核心要点（校对文本）
{_bullet_list(points)}

## 可复用资产清单（关键词回捞）
{_asset_section_markdown(assets)}

## 帧证据
{frame_evidence}

## 帧 OCR 校对文本
{clean_frame_ocr_text or "暂未识别到帧中文字。"}

## 需要二次验证
- 原视频中的示例是否完整覆盖关键条件。
- 方法是否依赖特定模型、平台版本或作者经验。
- 是否能通过本地项目样例复现。
- 本报告已做机器校对；提示词、参数、软件界面文字仍需结合原始帧证据或视觉模型复核。

## 关联项目
{_bullet_list(projects)}

## 完整转写 / 配文
{_full_content_block(clean_transcript)}
"""

    suggestion_content = f"""{_frontmatter(**{**common_fm, "type": "project-suggestion-card"})}
# 项目优化建议卡：{title}

## 推荐关联项目
{_bullet_list(projects)}

## 建议动作
{project_optimization}

## Worklist 草案
{_bullet_list(standard_worklist)}

## 可复用资产
{_video_asset_markdown(video_assets)}

## 证据
- 完整爬取：[[{knowledge_note.stem}]]
- 学习报告：[[{study_report.stem}]]
- 抖音链接：{source_url or "未记录"}
"""

    return SikuReportPaths(
        knowledge_note=_write(knowledge_note, knowledge_content),
        study_report=_write(study_report, study_content),
        project_suggestion=_write(project_suggestion, suggestion_content),
    )
