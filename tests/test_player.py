import json
from pathlib import Path

import pytest

from yt_ruby_subs import player


def test_parse_vtt_cues_supports_cue_ids_and_hourless_timestamps() -> None:
    text = """WEBVTT

cue-1
00:01.000 --> 00:02.500
Hello
world

01:02:03.000 --> 01:02:04.000
Later
"""

    cues = player.parse_vtt_cues_from_text(text)

    assert cues == [
        {"start": 1.0, "end": 2.5, "text": "Hello\nworld"},
        {"start": 3723.0, "end": 3724.0, "text": "Later"},
    ]


def test_find_video_near_subtitle_prefers_matching_stem(tmp_path: Path) -> None:
    subtitle = tmp_path / "clip.ja.ruby.vtt"
    subtitle.write_text("WEBVTT\n", encoding="utf-8")
    other_video = tmp_path / "other.mkv"
    other_video.write_text("", encoding="utf-8")
    matching_video = tmp_path / "clip.mp4"
    matching_video.write_text("", encoding="utf-8")

    assert player.find_video_near_subtitle(subtitle) == matching_video


def test_find_source_url_prefers_manifest(tmp_path: Path) -> None:
    subtitle = tmp_path / "clip.vtt"
    subtitle.write_text("WEBVTT\n", encoding="utf-8")
    (tmp_path / "download-manifest.json").write_text(
        json.dumps({"url": "https://www.youtube.com/watch?v=abc123"}),
        encoding="utf-8",
    )
    (tmp_path / "clip.info.json").write_text(
        json.dumps({"webpage_url": "https://example.com/fallback"}),
        encoding="utf-8",
    )

    assert player.find_source_url_near_subtitle(subtitle) == "https://www.youtube.com/watch?v=abc123"


def test_find_source_url_falls_back_to_info_json(tmp_path: Path) -> None:
    subtitle = tmp_path / "clip.vtt"
    subtitle.write_text("WEBVTT\n", encoding="utf-8")
    (tmp_path / "download-manifest.json").write_text("{bad", encoding="utf-8")
    (tmp_path / "a.info.json").write_text("{bad", encoding="utf-8")
    (tmp_path / "b.info.json").write_text(
        json.dumps({"original_url": "https://example.com/video"}),
        encoding="utf-8",
    )

    assert player.find_source_url_near_subtitle(subtitle) == "https://example.com/video"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.youtube.com/watch?v=abc123&feature=share", "abc123"),
        ("https://youtu.be/xyz789", "xyz789"),
        ("https://example.com/watch?v=nope", None),
        (None, None),
    ],
)
def test_extract_youtube_video_id(url: str | None, expected: str | None) -> None:
    assert player.extract_youtube_video_id(url) == expected


def test_generate_player_page_writes_local_video_config(tmp_path: Path) -> None:
    video = tmp_path / "clip 1.mp4"
    video.write_text("", encoding="utf-8")
    subtitle = tmp_path / "clip.ja.vtt"
    subtitle.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n</script><b>字幕</b>\n",
        encoding="utf-8",
    )
    html_path = tmp_path / "nested" / "player.html"

    result = player.generate_player_page(video_file=video, subtitle_file=subtitle, html_path=html_path)

    page = html_path.read_text(encoding="utf-8")
    assert result.html_path == html_path
    assert "clip%201.mp4" in page
    assert "<\\/script><b>字幕<\\/b>" in page
    assert "Ruby Subtitle Player" in page


def test_path_to_href_quotes_spaces_and_preserves_url_safe_chars() -> None:
    assert player.path_to_href(r"folder\clip 1 [draft].mp4") == "folder/clip%201%20[draft].mp4"
