import html
import json
import os
import re
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from .constants import VIDEO_EXTENSIONS
from .models import PlayerResult

TIMECODE_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}(?::\d{2})?\.\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}(?::\d{2})?\.\d{3})"
)
TEMPLATE_NAME = "player_template.html"


def generate_player_page(
    *, video_file: Path | None, subtitle_file: Path, html_path: Path
) -> PlayerResult:
    html_path.parent.mkdir(parents=True, exist_ok=True)
    video_rel = os.path.relpath(video_file, html_path.parent) if video_file else ""
    cues = parse_vtt_cues(subtitle_file)
    source_url = find_source_url_near_subtitle(subtitle_file)
    youtube_id = extract_youtube_video_id(source_url) if source_url else None

    page = build_player_html(
        page_title=f"{(video_file.stem if video_file else subtitle_file.stem)} - Ruby Subtitle Player",
        local_video_src=path_to_href(video_rel) if video_rel else "",
        video_label=video_file.name if video_file else "YouTube",
        subtitle_label=subtitle_file.name,
        cues=cues,
        source_url=source_url,
        youtube_id=youtube_id,
    )
    html_path.write_text(page, encoding="utf-8")
    return PlayerResult(
        html_path=html_path,
        video_path=video_file,
        subtitle_path=subtitle_file,
    )


def build_player_html(
    *,
    page_title: str,
    local_video_src: str,
    video_label: str,
    subtitle_label: str,
    cues: list[dict[str, object]],
    source_url: str | None,
    youtube_id: str | None,
) -> str:
    config = {
        "pageTitle": page_title,
        "localVideoSrc": local_video_src,
        "videoLabel": video_label,
        "subtitleLabel": subtitle_label,
        "sourceUrl": source_url or "",
        "youtubeId": youtube_id or "",
        "cues": cues,
    }
    # ``</`` is escaped so embedding the JSON inside <script> can never close the tag early.
    config_json = json.dumps(config, ensure_ascii=False).replace("</", "<\\/")
    template = (
        resources.files(__package__).joinpath(TEMPLATE_NAME).read_text(encoding="utf-8")
    )
    return template.replace("__PAGE_TITLE__", html.escape(page_title)).replace(
        "__CONFIG_JSON__", config_json
    )


def parse_vtt_cues(subtitle_file: Path) -> list[dict[str, object]]:
    return parse_vtt_cues_from_text(subtitle_file.read_text(encoding="utf-8-sig"))


def parse_vtt_cues_from_text(text: str) -> list[dict[str, object]]:
    normalized = normalize_vtt_newlines(text)
    return [
        cue
        for block in split_vtt_blocks(normalized)
        if (cue := parse_vtt_cue_block(block)) is not None
    ]


def normalize_vtt_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def split_vtt_blocks(text: str) -> list[str]:
    return re.split(r"\n\s*\n", text)


def parse_vtt_cue_block(block: str) -> dict[str, object] | None:
    lines = [line for line in block.split("\n") if line.strip()]
    if not lines or lines[0].startswith("WEBVTT"):
        return None

    timing = extract_timing_line(lines)
    if timing is None:
        return None
    timing_line, text_lines = timing

    match = TIMECODE_RE.match(timing_line)
    if not match:
        return None

    return {
        "start": timestamp_to_seconds(match.group("start")),
        "end": timestamp_to_seconds(match.group("end")),
        "text": "\n".join(text_lines).strip(),
    }


def extract_timing_line(lines: list[str]) -> tuple[str, list[str]] | None:
    if len(lines) >= 2 and "-->" not in lines[0] and "-->" in lines[1]:
        return lines[1], lines[2:]
    if "-->" in lines[0]:
        return lines[0], lines[1:]
    return None


def timestamp_to_seconds(timestamp: str) -> float:
    parts = timestamp.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = int(parts[0]), int(parts[1]), float(parts[2])
    else:
        hours, minutes, seconds = 0, int(parts[0]), float(parts[1])
    return hours * 3600 + minutes * 60 + seconds


def find_video_near_subtitle(subtitle_file: Path) -> Path | None:
    candidates = sorted(
        path
        for path in subtitle_file.parent.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )
    if not candidates:
        return None

    stem = subtitle_file.stem
    for candidate in candidates:
        if candidate.stem in stem or stem in candidate.stem:
            return candidate
    return candidates[0]


def find_source_url_near_subtitle(subtitle_file: Path) -> str | None:
    manifest = subtitle_file.parent / "download-manifest.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            url = data.get("url")
            if isinstance(url, str) and url:
                return url
        except json.JSONDecodeError:
            pass

    for info_path in sorted(subtitle_file.parent.glob("*.info.json")):
        try:
            data = json.loads(info_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for key in ("webpage_url", "original_url", "url"):
            value = data.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
    return None


def extract_youtube_video_id(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "youtube.com" in host:
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        return video_id or None
    if "youtu.be" in host:
        return parsed.path.strip("/") or None
    return None


def path_to_href(path: str) -> str:
    return quote(path.replace("\\", "/"), safe="/-._~!$&'()*+,;=:@[]")
