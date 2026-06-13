# yt-ruby-subs

Chinese: [README.zh-CN.md](README.zh-CN.md)

`yt-ruby-subs` downloads video subtitles with `yt-dlp`, then asks Codex, Claude Code, or an OpenAI-compatible chat API to produce:

- a corrected WebVTT transcript
- a WebVTT file with `<ruby>` and `<rt>` readings
- a local HTML player with clickable subtitle lines

It defaults to Japanese subtitles. Use `--lang` for any language expression accepted by `yt-dlp --sub-langs`.

## Requirements

- Python 3.13
- `uv`
- `yt-dlp`
- One generation backend:
  - `codex`
  - `claude`
  - an OpenAI-compatible chat API key

For `--provider api`, set one of these environment variables:

```powershell
$env:YT_RUBY_SUBS_API_KEY = "your_api_key"
$env:OPENROUTER_API_KEY = "your_openrouter_key"
$env:OPENAI_API_KEY = "your_openai_key"
```

The default API endpoint in `defaults.json` is OpenRouter:

```text
https://openrouter.ai/api/v1/chat/completions
```

Override it with `--api-base-url` or a config file.

## Quick start

Download a video, generate Japanese ruby subtitles, and write a player page:

```bash
uv run yt-ruby-subs run "https://example.com/video" --provider codex --lang ja
```

Use Claude Code instead:

```bash
uv run yt-ruby-subs run "https://example.com/video" --provider claude --lang ja
```

Use a chat API:

```bash
uv run yt-ruby-subs run "https://example.com/video" --provider api --lang ja
```

## Commands

Show help:

```bash
uv run yt-ruby-subs --help
```

Download subtitles and video:

```bash
uv run yt-ruby-subs download "https://example.com/video" --lang ja
```

Download subtitles only:

```bash
uv run yt-ruby-subs download "https://example.com/video" --lang ja --no-video
```

Generate from an existing subtitle file:

```bash
uv run yt-ruby-subs generate ".\downloads\example\video.ja.vtt" --provider codex
```

Use a custom OpenAI-compatible endpoint:

```bash
uv run yt-ruby-subs generate ".\downloads\example\video.ja.vtt" --provider api --api-base-url "https://openrouter.ai/api/v1/chat/completions"
```

Build a player from an existing video and subtitle pair:

```bash
uv run yt-ruby-subs player ".\downloads\example\video.webm" ".\downloads\example\video.ja.ruby.vtt"
```

## Output files

`run` writes files under `downloads/<title timestamp>/` by default. `generate` writes next to the input subtitle unless you pass `--output-dir`.

Typical outputs:

- `<name>.ruby.corrected.vtt`: corrected transcript
- `<name>.ruby.vtt`: ruby subtitle file
- `<name>.ruby.summary.txt`: short clip summary
- `<name>.ruby.player.html`: local player page
- `<name>.ruby.manifest.json`: generation details
- `download-manifest.json`: download details

Generation runs in stages. If a run is interrupted after `<name>.ruby.corrected.vtt` or `<name>.ruby.vtt` is written, rerun the same command and it will reuse the existing stage output.

Generated WebVTT is checked before it is written. A file with zero cues fails the run. Softer problems, such as empty cues or timing issues, are printed as `warning:` lines.

## Player controls

The generated `.player.html` works with a local video file. If only a YouTube source is available, it embeds the YouTube player.

Click a subtitle line to jump to that cue. The current line scrolls into view, and word timestamps are highlighted when the subtitle file has them.

| Key | Action |
| --- | --- |
| `Space` | Play or pause |
| `Left` / `Right` | Previous or next line |
| `R` | Repeat the current line |
| `L` | Loop the current line |
| `P` | Auto-pause after each line |
| `F` | Show or hide furigana |
| `-` / `=` | Change playback speed from 0.5x to 1.5x |
| `Alt+O` | Open the original video page |

## Configuration

Backend defaults live in `defaults.json` at the project root:

- `codex`: `gpt-5.5`
- `claude`: `best`
- `api`: no model unless you pass `--model` or set one in the config file

Use `--config` with `generate` or `run` to load another config file:

```bash
uv run yt-ruby-subs run "https://example.com/video" --config ".\my-config.json"
```

Config files can list only the keys you want to change:

```json
{
  "models": {
    "codex": "gpt-5.5"
  }
}
```

Model and endpoint precedence:

- model: `--model` > config file
- API endpoint: `--api-base-url` > config file

## Development

Install the project and dev tools:

```bash
uv sync --group dev
```

Run the lightweight checks:

```bash
uv run ruff check .
uv run pytest
uv run python -m compileall src
```
