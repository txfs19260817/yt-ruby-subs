from pathlib import Path
from typing import Any

from yt_ruby_subs import generate


def test_generate_outputs_reuses_existing_corrected_vtt(monkeypatch: Any, tmp_path: Path) -> None:
    subtitle_file = tmp_path / "video.ja.vtt"
    subtitle_file.write_text("WEBVTT\n\n00:00.000 --> 00:01.000\n仕事\n", encoding="utf-8")
    corrected_path = tmp_path / "video.ja.ruby.corrected.vtt"
    corrected_path.write_text("WEBVTT\n\n00:00.000 --> 00:01.000\n仕事\n", encoding="utf-8")

    schema_keys: list[tuple[str, ...]] = []

    def fake_backend(**kwargs: Any) -> dict[str, str]:
        keys = tuple(kwargs["schema"]["properties"])
        schema_keys.append(keys)
        if keys == ("webvtt",):
            return {"webvtt": "WEBVTT\n\n00:00.000 --> 00:01.000\n<ruby>仕事<rt>しごと</rt></ruby>"}
        if keys == ("summary",):
            return {"summary": "仕事についての短い字幕。"}
        raise AssertionError(f"unexpected backend call for keys: {keys}")

    monkeypatch.setattr(generate, "run_generation_backend", fake_backend)

    result = generate.generate_outputs(
        subtitle_file=subtitle_file,
        provider="claude",
        model="opus",
        api_base_url="",
        output_dir=tmp_path,
        base_name="",
        codex_bin="codex",
        claude_bin="claude",
        prompt_extra="",
    )

    assert result.corrected_subtitle_path == corrected_path
    assert result.webvtt_path.read_text(encoding="utf-8").startswith("WEBVTT")
    assert result.summary == "仕事についての短い字幕。"
    assert schema_keys == [("webvtt",), ("summary",)]
