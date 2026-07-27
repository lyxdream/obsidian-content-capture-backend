# 抖音内容提取（本地流水线）

从抖音分享链接或整段分享文案，在本地完成解析、下载与文案提取：

- **视频**：无水印下载 → FFmpeg 抽音频 → [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 转写 → [zhconv](https://github.com/Gowee/zhconv) 简体
- **视频画面**：FFmpeg 间隔抽帧 → macOS Vision OCR 识别画面文字 → 提取提示词、软件用法、参数、Skill/工作流线索
- **图文（note）**：提取 `desc` 配文并下载配图（不跑 Whisper，不做图片 OCR）

**无需登录 Cookie，无需硅基流动等付费语音 API。**

## 功能

| 能力 | 说明 |
|------|------|
| 链接 | `v.douyin.com` 短链、`www.douyin.com/note\|video`、`iesdouyin.com/share/...`、整段分享文案 |
| 解析 | 分享页 SSR `window._ROUTER_DATA`（备选 `RENDER_DATA`） |
| 下载 | 视频无水印 CDN；图文 `images/01.jpg` … |
| 输出 | 每作品一个文件夹 `output/{作品ID}_{标题}/` |

## 项目结构

```
obsidian-content-capture-backend/
├── script/                 # 核心库 + CLI（插件化时优先依赖此目录）
│   ├── douyin_resolver.py  # 分享页解析
│   ├── pipeline.py         # 主流水线
│   ├── transcriber.py      # Whisper + 简体
│   ├── downloader.py
│   ├── audio_extractor.py
│   └── main.py
├── docs/images/            # README 配图
├── web/                    # Flask Web + JSON API
│   ├── app.py
│   └── templates/index.html
├── main.py                 # 根目录 CLI 入口（自动使用 .venv）
├── run.sh / run-web.sh     # 包装脚本
├── output/                 # 提取结果（运行时生成）
├── requirements.txt
└── .cursor/skills/         # Cursor 开发用 Skill（可选）
```

`测试/` 目录为早期参考脚本，**与当前实现无关**，请勿混用。

## 环境要求

- **Python 3.10+**
- **[FFmpeg](https://ffmpeg.org/)**（仅视频流水线需要抽音频）
- 首次视频转写会从 Hugging Face 下载 Whisper 模型（需联网）

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg
```

## 安装

```bash
cd obsidian-content-capture-backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

| 依赖 | 用途 |
|------|------|
| `requests` | 请求分享页、下载文件 |
| `faster-whisper` | 本地语音转写 |
| `zhconv` | 繁体 → 简体 |
| `flask` | Web 界面 |
| `pyobjc-framework-Vision` | macOS 帧 OCR，识别视频画面里的提示词/参数/界面文字 |

> 若终端是 Conda `(base)` 且报 `No module named 'zhconv'`，请先 `source .venv/bin/activate`，或直接用 `./run.sh` / `python main.py`（会自动尝试 `.venv`）。

## 使用

### Web（推荐）

```bash
python web/app.py
# 或 ./run-web.sh
```

浏览器打开 **http://127.0.0.1:5050**（默认端口；macOS 上 5000 常被 AirPlay 占用）。

#### 使用步骤

1. **粘贴链接**  
   在「分享链接」输入框粘贴抖音短链（如 `https://v.douyin.com/...`）或整段分享文案。支持 `⌘ + Enter`（Windows：`Ctrl + Enter`）快捷提交。

2. **（可选）获取信息**  
   点击 **获取信息**，左侧「作品信息」会显示类型（视频/图文）、标题、作者、作品 ID；视频可在此 **下载无水印原视频**，无需转写时够用。

3. **选择 Whisper 模型**  
   输入框下方选择模型（默认 `small`）。越大越准、越慢；长视频可试 `base` / `tiny` 加快。

4. **提取文案**  
   点击 **提取文案**，开始完整流水线。右侧出现「提取中」与四步进度：
   - 解析分享链接 → 下载视频 → 提取音频 → 语音识别（图文作品跳过转写，通常几秒完成）

   ![Web 提取进行中](docs/images/web-extracting.png)

   > 视频转写可能需数分钟，请勿关闭页面；终端需保持 `python web/app.py` 运行。

5. **查看与导出结果**  
   完成后右侧「提取结果」显示简体文案与字数，可 **复制** 或 **下载** `transcript.txt`；本地文件在 `output/{作品ID}_{标题}/`。

   ![Web 提取完成](docs/images/web-result.png)

#### 界面说明

| 区域 | 作用 |
|------|------|
| 分享链接 | 输入 URL 或分享文案，选择模型并触发提取 |
| 作品信息 | 解析后的元数据；视频可单独下载无水印 MP4 |
| 提取中 / 提取结果 | 实时进度与最终文案（复制、下载） |

指定端口：`PORT=8080 python web/app.py`

### 飞书手机收件箱（马哥）

用于手机刷抖音时，把分享文案/链接发给飞书机器人「马哥」，先进入本地队列，再由 worker 后续下载、转写和入库。

#### 1. 推荐入口：长连接

```bash
export FEISHU_APP_SECRET="你的马哥 App Secret"
./run-feishu-ws-listener.sh
```

默认配置：

| 环境变量 | 默认值 | 说明 |
|------|------|------|
| `FEISHU_APP_ID` | `cli_aaab1c2d2c785bfc` | 马哥应用 ID |
| `FEISHU_APP_SECRET` | 无 | 马哥应用密钥，只从本机环境变量读取 |
| `VIDEO_INBOX_DIR` | `/Users/zhuchenyuan/AI/projects/司库/01-资料采集/Inbox/video-inbox` | 飞书队列目录 |
| `FEISHU_POLL_CHAT_ID` | `oc_705067992099413b7560f38fe3ea6c2a` | worker 主动轮询的马哥会话 ID，用于兜底长连接漏事件 |
| `FEISHU_POLL_LOOKBACK_SECONDS` | `3600` | 只补入最近 N 秒内的飞书消息 |

飞书开放平台里，事件订阅方式切到「使用长连接接收事件」，并保留 `im.message.receive_v1`。长连接不需要公网 URL，也不需要 Cloudflare tunnel；只要本机 listener 运行，手机发给「马哥」的消息就会进入本地队列。

接收成功后，机器人会回复：

```text
已接收：收到 N 个抖音链接，已进入短视频收件箱。处理完成后我会再回复。
```

回复依赖 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET` 获取 tenant access token。回执失败不会阻断入队，但日志或处理记录会保留 `reply_error` 便于排查。

#### 2. 备用入口：HTTP webhook

如果临时需要 webhook 模式：

```bash
./run-feishu-webhook.sh
```

本地服务回调路径为：

```text
http://127.0.0.1:5050/api/feishu/events/inbox20260712
```

飞书开放平台需要公网 URL。临时调试可另开终端：

```bash
cloudflared tunnel --protocol http2 --url http://127.0.0.1:5050
```

然后把生成的公网域名拼成：

```text
https://<cloudflared-domain>/api/feishu/events/inbox20260712
```

写入「马哥」事件订阅的请求地址。Cloudflare quick tunnel 是临时入口，Mac 休眠、终端关闭或域名变化后，需要重新填写飞书回调地址。

#### 3. 验证队列

手机端把抖音分享文案发给「马哥」后，本地会追加：

```text
$VIDEO_INBOX_DIR/feishu-events.jsonl
```

队列记录只保存必要字段：来源、状态、抖音链接、原始文本、飞书消息 ID、接收时间。

#### 4. 处理队列

先 dry-run 验证，不下载、不转写：

```bash
./run-feishu-worker.sh --dry-run --limit 5
```

确认无误后处理：

```bash
# 只采集素材，不跑 Whisper
./run-feishu-worker.sh --skip-transcribe --limit 1

# 完整下载 + Whisper 转写
./run-feishu-worker.sh --model small --limit 1

# 完整处理并尝试同步 gbrain
./run-feishu-worker.sh --model small --limit 1 --gbrain-capture
```

处理结果追加到：

```text
$VIDEO_INBOX_DIR/processed-events.jsonl
```

worker 会按「飞书消息 ID + 抖音链接」去重；失败记录不会阻止下次重试。`--dry-run` 产生的记录只用于 dry-run 去重，不会阻止正式处理。

为避免飞书长连接偶发漏事件，worker 每轮会先主动轮询 `FEISHU_POLL_CHAT_ID` 对应会话最近消息；如果发现最近 1 小时内有尚未入队的抖音链接，会补写到 `feishu-events.jsonl` 并发送「已接收」回执。长连接和轮询共用同一套 message_id 去重。

worker 每处理完一条链接，会回复原飞书消息：

```text
已处理完毕：https://v.douyin.com/...
学习报告：/Users/zhuchenyuan/AI/projects/司库/03-知识加工/蒸馏精华/短视频学习/...
```

如果处理失败，会回复 `处理失败` 和错误原因。历史已处理链接在后续轮询中只跳过，不重复发送回执，避免刷屏。

成功处理后会自动生成三类司库 Markdown：

| 类型 | 目录 |
|------|------|
| 完整爬取内容 | `02-知识笔记/短视频爬取/` |
| 学习蒸馏 | `03-知识加工/蒸馏精华/短视频学习/` |
| 项目建议 | `03-知识加工/智能建议/项目优化建议/` |

如果加 `--gbrain-capture`，worker 会对学习蒸馏报告执行 `gbrain capture --file ... --source default`。如果本机 gbrain/PGLite 被其他进程锁住，处理记录会保留 `gbrain_error`，报告文件仍然已经落入司库。

视频类内容还会在本地输出目录生成画面证据：

| 文件 | 说明 |
|------|------|
| `frames/frame_0001.jpg` 等 | 每 2 秒抽取一张视频帧 |
| `frames/manifest.json` | 抽帧清单 |
| `frames/frame_ocr.txt` | 帧 OCR 文本，包含画面中的提示词、参数、软件界面文字 |
| `frames/frame_ocr.json` | 结构化 OCR 结果 |

学习报告会包含「可复用资产清单」「帧证据」「帧 OCR 文本」「完整转写 / 配文」。其中可复用资产清单会按提示词模板、软件/工具用法、Skill/工作流、参数/语法拆分。OCR 可能存在错字，报告会保留帧证据，便于回看核对。

### 命令行

```bash
# 任选一种（均建议在项目根目录执行）
python main.py "https://v.douyin.com/xxxxx/"
python -m script "https://v.douyin.com/xxxxx/"
./run.sh "https://v.douyin.com/xxxxx/"

# 图文 note 页
python main.py "https://www.douyin.com/note/7640701464617132402"

# 整段分享文案（内含短链即可）
python main.py "7.48 复制打开抖音… https://v.douyin.com/xxxxx/ …"

# 交互输入（无参数时从 stdin 读取）
python main.py

# 指定 Whisper 模型（仅视频）
python main.py --model base "https://v.douyin.com/xxxxx/"
```

可选参数：`--output`、 `--device`、`--compute-type`（见 `python -m script --help`）。

## 输出结构

**视频：**

```
output/{作品ID}_{标题}/
├── video.mp4
├── audio.wav
├── download_url.txt
├── transcript.txt
├── transcript_segments.json
└── meta.json
```

**图文：**

```
output/{作品ID}_{标题}/
├── images/01.jpg …
├── image_urls.txt
├── transcript.txt
└── meta.json
```

`transcript.txt` 含元数据头与 `--- 文案 ---` 分隔的正文。

## HTTP API（供集成 / 插件参考）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/health` | 健康检查，本地 Whisper |
| `POST` | `/api/video/info` | JSON `{ "url": "..." }`，仅元数据 |
| `POST` | `/api/video/extract` | JSON `{ "url": "...", "model": "small" }`，完整流水线 |
| `GET` | `/api/video/download` | 查询参数 `url`、`filename`，代理下载视频 |
| `GET` | `/files/<path>` | 访问 `output/` 下已生成文件 |

## 在代码中调用

```python
from script.config import Settings
from script.douyin_resolver import resolve_douyin_share
from script.pipeline import process_douyin_share

# 仅解析，不下载、不转写
meta = resolve_douyin_share("https://v.douyin.com/xxxxx/")
print(meta.title, meta.content_type, meta.download_url)

# 完整流水线
out_dir = process_douyin_share(
    "https://v.douyin.com/xxxxx/",
    settings=Settings(whisper_model="small"),
)
```

## 技术说明

| 环节 | 实现 |
|------|------|
| 解析 | 移动端 UA 打开 `iesdouyin.com/share/...`，读 SSR JSON；`www.douyin.com/note\|video` 会自动转换 |
| 无水印 | `play_addr` → `play` 端点（`playwm` → `play`） |
| 视频文案 | CDN 下载 → FFmpeg 16kHz wav → faster-whisper → zhconv |
| 图文文案 | 直接使用 `desc`；图片直链批量下载 |

## 常见问题

| 现象 | 建议 |
|------|------|
| 解析失败 | 检查链接；`note`/`video` 页需能转到 `iesdouyin.com/share/...` |
| 视频很慢 | CPU + `small` 模型下长视频数分钟正常，可试 `tiny` / `base` |
| 终端 `float16 → float32` | CPU 上 ctranslate2 自动降级，可忽略 |
| Web 长时间无响应 | 同步处理中，视频转写完成前页面不会更新 |
| 配图无文字 | 题本在图片里，当前未做 OCR |

## Obsidian 插件

配套插件：[obsidian-douyin-capture](https://github.com/lyxdream/obsidian-douyin-capture)。插件与后端的 API / Vault 约定见插件仓库 [`docs/obsidian-plugin-contract.md`](../obsidian-douyin-capture/docs/obsidian-plugin-contract.md)。

## 后续规划

业务逻辑集中在 `script/`，计划通过 adapter（MCP / 子进程 / Obsidian 等）对外提供插件能力；`web/` 仅作演示与本地调试。

## 许可与声明

仅供学习与研究。请遵守相关法律法规与平台规则，勿用于侵权或违法用途。
