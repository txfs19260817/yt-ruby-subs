from pathlib import Path

from yt_ruby_subs.prompts import (
    build_corrected_prompt,
    build_ruby_prompt,
    build_summary_prompt,
)


def test_build_corrected_prompt_uses_source_subtitle(tmp_path: Path) -> None:
    subtitle_file = tmp_path / "video.ja.vtt"
    subtitle_file.write_text(
        "WEBVTT\n\n00:00.000 --> 00:01.000\n仕事\n", encoding="utf-8"
    )

    prompt = build_corrected_prompt(subtitle_file, "keep short cues")

    assert "corrected_vtt" in prompt
    assert "keep short cues" in prompt
    assert "<subtitle_file>" in prompt
    assert "仕事" in prompt


def test_build_corrected_prompt_includes_ocr_reference(tmp_path: Path) -> None:
    subtitle_file = tmp_path / "video.ja.vtt"
    subtitle_file.write_text(
        "WEBVTT\n\n00:00.000 --> 00:01.000\n誤字\n", encoding="utf-8"
    )
    ocr_reference = tmp_path / "video.hard-sub-ocr.txt"
    ocr_reference.write_text("[000001]\n正字\n", encoding="utf-8")

    prompt = build_corrected_prompt(subtitle_file, "", ocr_reference_file=ocr_reference)

    assert "<ocr_reference>" in prompt
    assert "正字" in prompt
    assert "Use OCR as a correction reference" in prompt


def test_build_ruby_prompt_uses_corrected_vtt() -> None:
    corrected_vtt = "WEBVTT\n\n00:00.000 --> 00:01.000\n仕事\n"

    prompt = build_ruby_prompt(corrected_vtt)

    assert "webvtt" in prompt
    assert "<corrected_vtt>" in prompt
    assert corrected_vtt in prompt


def test_build_summary_prompt_uses_corrected_vtt() -> None:
    corrected_vtt = "WEBVTT\n\n00:00.000 --> 00:01.000\n仕事\n"

    prompt = build_summary_prompt(corrected_vtt)

    assert "summary" in prompt
    assert "<corrected_vtt>" in prompt
    assert corrected_vtt in prompt
