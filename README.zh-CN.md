# yt-ruby-subs

英文版: [README.md](README.md)

`yt-ruby-subs` 用 `yt-dlp` 下载视频字幕，然后把字幕交给 Codex、Claude Code 或 OpenAI 兼容的聊天 API。它会生成:

- 修正后的 WebVTT 字幕
- 带 `<ruby>` 和 `<rt>` 注音的 WebVTT 字幕
- 可以点击字幕跳转播放位置的本地 HTML 播放器

默认字幕语言是日语。需要其他语言时，用 `--lang` 传入 `yt-dlp --sub-langs` 支持的表达式。

## 环境要求

- Python 3.13
- `uv`
- `yt-dlp`
- 一个生成后端:
  - `codex`
  - `claude`
  - OpenAI 兼容的聊天 API key

使用 `--provider api` 时，设置下面任意一个环境变量:

```powershell
$env:YT_RUBY_SUBS_API_KEY = "your_api_key"
$env:OPENROUTER_API_KEY = "your_openrouter_key"
$env:OPENAI_API_KEY = "your_openai_key"
```

`defaults.json` 里的默认 API 地址是 OpenRouter:

```text
https://openrouter.ai/api/v1/chat/completions
```

可以用 `--api-base-url` 或配置文件改成其他 OpenAI 兼容接口。

## 快速开始

下载视频，生成日语 ruby 字幕，并写出播放器页面:

```bash
uv run yt-ruby-subs run "https://example.com/video" --provider codex --lang ja
```

改用 Claude Code:

```bash
uv run yt-ruby-subs run "https://example.com/video" --provider claude --lang ja
```

使用聊天 API:

```bash
uv run yt-ruby-subs run "https://example.com/video" --provider api --lang ja
```

## 常用命令

查看帮助:

```bash
uv run yt-ruby-subs --help
```

下载视频和字幕:

```bash
uv run yt-ruby-subs download "https://example.com/video" --lang ja
```

只下载字幕:

```bash
uv run yt-ruby-subs download "https://example.com/video" --lang ja --no-video
```

从已有字幕生成:

```bash
uv run yt-ruby-subs generate ".\downloads\example\video.ja.vtt" --provider codex
```

使用自定义 OpenAI 兼容接口:

```bash
uv run yt-ruby-subs generate ".\downloads\example\video.ja.vtt" --provider api --api-base-url "https://openrouter.ai/api/v1/chat/completions"
```

用已有视频和字幕生成播放器:

```bash
uv run yt-ruby-subs player ".\downloads\example\video.webm" ".\downloads\example\video.ja.ruby.vtt"
```

## OCR 参考文本

如果视频自带日语硬字幕，`run` 可以在下载视频后 OCR 视频下方区域，并把识别文本交给 AI 修正字幕时参考。
默认裁剪视频下方 1/5。需要调整时用 `--ocr-bottom-ratio`，需要完整 ffmpeg crop 表达式时用 `--ocr-crop`。
OCR 抽帧默认还会用 ffmpeg 做轻量帧去重；如果误删了你想检查的帧，可以加 `--no-ocr-frame-dedupe` 关闭。

Tesseract:

```bash
uv sync --extra ocr
uv run yt-ruby-subs run "https://example.com/video" --provider codex --ocr
```

这条路径还需要 `ffmpeg`、Tesseract，以及日语 Tesseract 语言数据。

PaddleOCR-VL 1.6:

```bash
uv sync --extra paddleocr-vl
uv run yt-ruby-subs run "https://example.com/video" --provider codex --ocr --ocr-engine paddleocr-vl
```

本项目约定 PaddleOCR-VL 只走 GPU。`paddleocr-vl` extra 会从 Paddle 的 CUDA 13.0 包索引安装 `paddlepaddle-gpu`，CLI 默认 `--paddleocr-vl-device gpu`。如果你的 NVIDIA 驱动需要其他 CUDA wheel，修改 `pyproject.toml` 里的 `paddle-cu130` 索引。

使用 VLM service 后端:

```bash
uv run yt-ruby-subs run "https://example.com/video" --ocr --ocr-engine paddleocr-vl --paddleocr-vl-backend vllm-server --paddleocr-vl-server-url "http://localhost:8000/v1" --paddleocr-vl-api-model-name "PaddlePaddle/PaddleOCR-VL-1.6"
```

复用已有 OCR 文件:

```bash
uv run yt-ruby-subs generate ".\downloads\example\video.ja.vtt" --ocr-reference ".\downloads\example\video.hard-sub-ocr.txt"
```

## 输出文件

`run` 默认写入 `downloads/<标题 时间戳>/`。`generate` 默认写到输入字幕旁边，除非你传入 `--output-dir`。

常见输出:

- `<video>.hard-sub-ocr.txt`: 可选的硬字幕 OCR 参考文本
- `<name>.ruby.corrected.vtt`: 修正后的字幕
- `<name>.ruby.vtt`: 带 ruby 注音的字幕
- `<name>.ruby.summary.txt`: 视频简介
- `<name>.ruby.player.html`: 本地播放器
- `<name>.ruby.manifest.json`: 生成记录
- `download-manifest.json`: 下载记录

生成流程会分阶段写入文件。如果运行在写出 `<name>.ruby.corrected.vtt` 或 `<name>.ruby.vtt` 后中断，重新运行同一条命令会复用已经完成的阶段。

写入前会检查生成的 WebVTT。没有任何 cue 的文件会直接失败。空 cue、时间顺序异常等问题会以 `warning:` 打印出来。

## 播放器快捷键

生成的 `.player.html` 可以播放本地视频。如果只有 YouTube 来源，它会嵌入 YouTube 播放器。

点击字幕行可以跳到对应位置。当前字幕会自动滚入视图；如果字幕里有逐词时间戳，播放器会同步高亮词。

| 按键 | 动作 |
| --- | --- |
| `Space` | 播放或暂停 |
| `Left` / `Right` | 上一句或下一句 |
| `R` | 重播当前句 |
| `L` | 循环当前句 |
| `P` | 每句结束后自动暂停 |
| `F` | 显示或隐藏假名注音 |
| `-` / `=` | 调整速度，范围 0.5x 到 1.5x |
| `Alt+O` | 打开原视频页面 |

## 配置

后端默认值在项目根目录的 `defaults.json`:

- `codex`: `gpt-5.5`
- `claude`: `best`
- `api`: 不指定模型，除非你传入 `--model` 或在配置文件里设置

`generate` 和 `run` 可以用 `--config` 加载另一个配置文件:

```bash
uv run yt-ruby-subs run "https://example.com/video" --config ".\my-config.json"
```

配置文件可以只写需要覆盖的字段:

```json
{
  "models": {
    "codex": "gpt-5.5"
  }
}
```

模型和接口地址的优先级:

- 模型: `--model` > 配置文件
- API 地址: `--api-base-url` > 配置文件

## 开发

安装项目和开发工具:

```bash
uv sync --group dev
```

运行轻量检查:

```bash
uv run ruff check .
uv run pytest
uv run python -m compileall src
```
