import json
from datetime import datetime
from pathlib import Path
from typing import Any

from yt_ruby_subs import download


class FixedDatetime:
    @classmethod
    def now(cls) -> datetime:
        return datetime(2026, 1, 2, 3, 4, 5)


def test_download_with_yt_dlp_finalizes_directory_and_manifest(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    captured_command: list[str] = []
    monkeypatch.setattr(download, "datetime", FixedDatetime)
    monkeypatch.setattr(download, "resolve_command", lambda raw, *, windows_preferred: "yt-dlp-bin")

    def fake_run_subprocess(command: list[str], *, cwd: Path, **kwargs: Any) -> None:
        captured_command.extend(command)
        (cwd / "Lesson.ja.auto.srt").write_text("auto", encoding="utf-8")
        (cwd / "Lesson.ja.vtt").write_text("WEBVTT\n", encoding="utf-8")
        (cwd / "Lesson [abc].mp4").write_text("", encoding="utf-8")
        (cwd / "Lesson.info.json").write_text(
            json.dumps({"title": "Bad:/ Title*"}),
            encoding="utf-8",
        )

    monkeypatch.setattr(download, "run_subprocess", fake_run_subprocess)

    result = download.download_with_yt_dlp(
        url="https://example.com/video",
        lang="ja,en",
        output_root=tmp_path,
        job_name="job/name",
        no_video=True,
        subtitle_format="vtt/srt/best",
        yt_dlp_bin="yt-dlp",
    )

    assert captured_command[0] == "yt-dlp-bin"
    assert "--skip-download" in captured_command
    assert result.work_dir.name == "Bad Title 20260102-030405 - job name"
    assert result.selected_subtitle == result.work_dir / "Lesson.ja.vtt"
    manifest = json.loads((result.work_dir / "download-manifest.json").read_text(encoding="utf-8"))
    assert manifest["url"] == "https://example.com/video"
    assert manifest["selected_subtitle"].endswith("Lesson.ja.vtt")
    assert manifest["created_at"] == "2026-01-02T03:04:05"


def test_choose_subtitle_scores_language_format_and_auto_penalty() -> None:
    files = [
        Path("clip.en.srt"),
        Path("clip.ja.auto.vtt"),
        Path("clip.ja.vtt"),
        Path("clip.ja.orig.ass"),
    ]

    assert download.choose_subtitle(files, "ja,en") == Path("clip.ja.vtt")
    assert download.choose_subtitle([], "ja") is None


def test_choose_download_title_uses_json_title_then_fallbacks(tmp_path: Path) -> None:
    bad_info = tmp_path / "bad.info.json"
    bad_info.write_text("{bad", encoding="utf-8")
    good_info = tmp_path / "good.info.json"
    good_info.write_text(json.dumps({"title": "  Config Title  "}), encoding="utf-8")
    video = tmp_path / "Video Name [abc123].mp4"
    video.write_text("", encoding="utf-8")
    subtitle = tmp_path / "Fallback.ja.ruby.corrected.vtt"
    subtitle.write_text("", encoding="utf-8")

    assert download.choose_download_title([bad_info, good_info], [video], subtitle) == "Config Title"
    assert download.choose_download_title([bad_info], [video], subtitle) == "Video Name"
    assert download.choose_download_title([bad_info], [], subtitle) == "Fallback"
    assert download.choose_download_title([bad_info], [], None) == "download"


def test_output_directory_helpers_sanitize_and_avoid_collisions(tmp_path: Path) -> None:
    existing = tmp_path / "Bad Name 20260102-030405"
    existing.mkdir()
    current = tmp_path / "__tmp__"
    current.mkdir()

    assert download.sanitize_dir_name(' Bad:/Name*... ') == "Bad Name"
    assert (
        download.build_output_dir_name(title="Bad:/Name*", timestamp="20260102-030405", job_name="")
        == "Bad Name 20260102-030405"
    )

    target = download.finalize_download_dir(
        current_dir=current,
        root=tmp_path,
        title="Bad:/Name*",
        timestamp="20260102-030405",
        job_name="",
    )

    assert target == tmp_path / "Bad Name 20260102-030405 (2)"
    assert target.exists()
