---
name: subtitle-correction
description: Correct generated yt-ruby-subs subtitle outputs after a user points out a wrong transcript, wording, punctuation, or furigana/ruby annotation. Use when asked to fix subtitles, edit a generated WebVTT cue, repair corrected_vtt versus ruby_vtt mismatch, or update the local player after manual subtitle corrections. Designed for both Codex and Claude Code because it relies on repo files and CLI commands, not vendor-specific agent features.
---

# Subtitle Correction

## Goal

Apply small human-directed subtitle fixes without rerunning the expensive model stages. Keep the plain corrected transcript, ruby WebVTT, HTML player, and manifest consistent.

## Workflow

1. Locate the generated outputs.
   - Prefer files under `downloads/`.
   - Identify the matching set by base name:
     - `<base>.corrected.vtt`
     - `<base>.vtt`
     - `<base>.summary.txt`
     - `<base>.player.html`
     - `<base>.manifest.json`
   - Treat the original downloaded subtitle, such as `<video>.ja.vtt`, as source material. Do not edit it unless the user explicitly asks.

2. Find the target cue before editing.
   - Search for both the wrong text and the requested replacement.
   - Inspect surrounding cue timestamps and nearby lines.
   - If the correction spans a line break inside one cue, keep the cue timestamp and cue count stable. Changing line breaks inside the cue is acceptable when it makes the corrected text match the user's requested wording.

3. Edit both subtitle layers.
   - In `<base>.corrected.vtt`, write plain Japanese text only. Do not add `<ruby>` markup.
   - In `<base>.vtt`, make the same plain-text correction and add ruby markup only where needed.
   - The plain text after stripping ruby tags must match the corrected VTT exactly for each cue.
   - Do not rewrite unrelated cues or normalize punctuation outside the requested correction.

4. Rebuild derived files without calling the model.
   - Before using `generate`, verify that `<base>.corrected.vtt`, `<base>.vtt`, and `<base>.summary.txt` already exist. The staged generator reuses existing stage files and only rebuilds the player and manifest.
   - Run from the project root:

```powershell
$provider = "codex"  # or "claude" to preserve the original output provider
uv run yt-ruby-subs generate "<source-subtitle.vtt>" --provider $provider --output-dir "<output-dir>" --base-name "<base>"
```

   - The provider value is only recorded in the manifest when all stage files already exist; choose the original provider when known. It should not trigger a model call. If a stage file is missing, stop and use the `player` command instead unless the user explicitly wants regeneration.

```powershell
uv run yt-ruby-subs player "<base>.vtt" --output-html "<base>.player.html"
```

5. Validate consistency.
   - Run the project validator against the corrected and ruby WebVTT files:

```powershell
@'
from pathlib import Path
from yt_ruby_subs.generate import validate_outputs

corrected = Path(r"<base>.corrected.vtt")
ruby = Path(r"<base>.vtt")
warnings = validate_outputs(
    corrected.read_text(encoding="utf-8"),
    ruby.read_text(encoding="utf-8"),
)
print(warnings)
'@ | uv run python -
```

   - Expected result for a clean manual fix is `[]`.
   - Search the corrected VTT, ruby VTT, and player HTML for stale wrong text before finishing.

## Ruby Markup Rules

- Annotate kanji words that need furigana, not kana-only text.
- Keep the user's corrected wording as the source of truth. Do not replace it with a smoother paraphrase.
- Use valid WebVTT-safe HTML:

```html
<ruby>同格<rt>どうかく</rt></ruby>
```

- If unsure about a reading, prefer a conservative correction in `corrected.vtt` and ask before adding uncertain furigana.

## Reporting

Finish with the changed files, the corrected text, whether the player was rebuilt, and the validator result. Mention if the corrected outputs are ignored by git, because downloaded/generated media usually should not be committed.
