import argparse
from pathlib import Path

import pytest

from yt_ruby_subs import cli
from yt_ruby_subs.errors import CliError
from yt_ruby_subs.models import DownloadResult, GenerationResult, PlayerResult


def test_main_returns_success_and_handles_cli_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def success_func(args: argparse.Namespace) -> int:
        return 7

    class ErrorParser:
        def parse_args(self, argv: list[str] | None) -> argparse.Namespace:
            return argparse.Namespace(
                func=lambda args: (_ for _ in ()).throw(CliError("bad args"))
            )

    monkeypatch.setattr(cli, "build_parser", ErrorParser)
    assert cli.main(["anything"]) == 1
    assert "error: bad args" in capsys.readouterr().err

    class SuccessParser:
        def parse_args(self, argv: list[str] | None) -> argparse.Namespace:
            return argparse.Namespace(func=success_func)

    monkeypatch.setattr(cli, "build_parser", SuccessParser)
    assert cli.main(["anything"]) == 7


def test_main_handles_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class InterruptParser:
        def parse_args(self, argv: list[str] | None) -> argparse.Namespace:
            return argparse.Namespace(
                func=lambda args: (_ for _ in ()).throw(KeyboardInterrupt())
            )

    monkeypatch.setattr(cli, "build_parser", InterruptParser)

    assert cli.main(["anything"]) == 130
    assert "error: interrupted" in capsys.readouterr().err


def test_handle_download_calls_downloader_and_prints_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    subtitle = tmp_path / "clip.ja.vtt"
    video = tmp_path / "clip.mp4"
    result = DownloadResult(
        work_dir=tmp_path,
        video_files=[video],
        subtitle_files=[subtitle],
        selected_subtitle=subtitle,
        info_files=[],
    )
    captured: dict[str, object] = {}

    def fake_download_with_yt_dlp(**kwargs: object) -> DownloadResult:
        captured.update(kwargs)
        return result

    monkeypatch.setattr(cli, "download_with_yt_dlp", fake_download_with_yt_dlp)
    args = argparse.Namespace(
        url="https://example.com/video",
        lang="ja",
        output_root=tmp_path,
        job_name="job",
        no_video=True,
        subtitle_format="vtt",
        yt_dlp_bin="yt-dlp",
        yt_dlp_js_runtimes="node",
    )

    assert cli.handle_download(args) == 0

    assert captured["url"] == "https://example.com/video"
    output = capsys.readouterr().out
    assert "download_dir:" in output
    assert "subtitle:" in output
    assert "[selected]" in output


def test_handle_generate_loads_config_and_prints_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    subtitle = tmp_path / "clip.ja.vtt"
    subtitle.write_text("WEBVTT\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_generate_outputs(**kwargs: object) -> GenerationResult:
        captured.update(kwargs)
        return GenerationResult(
            corrected_subtitle_path=tmp_path / "clip.corrected.vtt",
            webvtt_path=tmp_path / "clip.ruby.vtt",
            provider=str(kwargs["provider"]),
            summary="short summary",
            player_path=tmp_path / "clip.player.html",
        )

    monkeypatch.setattr(
        cli,
        "load_config",
        lambda path: {"models": {"codex": "config-model"}, "api_base_url": "api"},
    )
    monkeypatch.setattr(cli, "generate_outputs", fake_generate_outputs)
    args = argparse.Namespace(
        subtitle_file=subtitle,
        config=None,
        provider="codex",
        model=None,
        api_base_url=None,
        output_dir=None,
        base_name="",
        codex_bin="codex",
        claude_bin="claude",
        prompt_extra="",
    )

    assert cli.handle_generate(args) == 0

    assert captured["subtitle_file"] == subtitle.resolve()
    assert captured["model"] == "config-model"
    output = capsys.readouterr().out
    assert "provider: codex" in output
    assert "player:" in output
    assert "summary: short summary" in output


def test_handle_generate_rejects_missing_subtitle(tmp_path: Path) -> None:
    args = argparse.Namespace(subtitle_file=tmp_path / "missing.vtt")

    with pytest.raises(CliError, match="subtitle file not found"):
        cli.handle_generate(args)


def test_handle_run_raises_when_no_subtitle_downloaded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli, "load_config", lambda path: {})
    monkeypatch.setattr(
        cli,
        "download_with_yt_dlp",
        lambda **kwargs: DownloadResult(
            work_dir=tmp_path,
            video_files=[],
            subtitle_files=[],
            selected_subtitle=None,
            info_files=[],
        ),
    )
    args = argparse.Namespace(
        config=None,
        url="https://example.com/video",
        lang="ja",
        output_root=tmp_path,
        job_name="",
        no_video=True,
        subtitle_format="vtt",
        yt_dlp_bin="yt-dlp",
        yt_dlp_js_runtimes="node",
    )

    with pytest.raises(CliError, match="no subtitle file was downloaded"):
        cli.handle_run(args)


def test_handle_run_generates_ocr_reference_before_generation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    subtitle = tmp_path / "clip.ja.vtt"
    subtitle.write_text("WEBVTT\n", encoding="utf-8")
    video = tmp_path / "clip.mp4"
    video.write_text("video", encoding="utf-8")
    captured: dict[str, object] = {}

    monkeypatch.setattr(cli, "load_config", lambda path: {})
    monkeypatch.setattr(
        cli,
        "download_with_yt_dlp",
        lambda **kwargs: DownloadResult(
            work_dir=tmp_path,
            video_files=[video],
            subtitle_files=[subtitle],
            selected_subtitle=subtitle,
            info_files=[],
        ),
    )

    def fake_run_hard_subtitle_ocr(**kwargs: object) -> Path:
        output_file = kwargs["output_file"]
        assert isinstance(output_file, Path)
        options = kwargs["options"]
        assert isinstance(options, cli.OcrOptions)
        assert options.engine == "paddleocr-vl"
        assert options.bottom_ratio == 0.2
        assert options.crop == ""
        assert options.frame_dedupe is True
        assert options.paddleocr_vl_device == "gpu"
        assert options.paddleocr_vl_backend == "vllm-server"
        output_file.write_text("硬字幕OCR\n", encoding="utf-8")
        return output_file

    def fake_generate_outputs(**kwargs: object) -> GenerationResult:
        captured.update(kwargs)
        return GenerationResult(
            corrected_subtitle_path=tmp_path / "clip.corrected.vtt",
            webvtt_path=tmp_path / "clip.ruby.vtt",
            provider=str(kwargs["provider"]),
            summary=None,
            player_path=None,
        )

    monkeypatch.setattr(cli, "run_hard_subtitle_ocr", fake_run_hard_subtitle_ocr)
    monkeypatch.setattr(cli, "generate_outputs", fake_generate_outputs)

    args = argparse.Namespace(
        config=None,
        url="https://example.com/video",
        lang="ja",
        output_root=tmp_path,
        job_name="",
        no_video=False,
        subtitle_format="vtt",
        yt_dlp_bin="yt-dlp",
        yt_dlp_js_runtimes="bun",
        ocr=True,
        ocr_engine="paddleocr-vl",
        ocr_lang="jpn",
        ocr_interval=1.0,
        ocr_bottom_ratio=0.2,
        ocr_crop="",
        ocr_frame_dedupe=True,
        ocr_output=None,
        ffmpeg_bin="ffmpeg",
        tesseract_bin="tesseract",
        paddleocr_vl_device="gpu",
        paddleocr_vl_backend="vllm-server",
        paddleocr_vl_server_url="http://localhost:8000/v1",
        paddleocr_vl_api_model_name="PaddlePaddle/PaddleOCR-VL-1.6",
        paddleocr_vl_api_key="",
        provider="codex",
        model=None,
        api_base_url=None,
        output_dir=None,
        base_name="",
        codex_bin="codex",
        claude_bin="claude",
        prompt_extra="",
        ocr_reference=None,
    )

    assert cli.handle_run(args) == 0

    expected_ocr = tmp_path / "clip.hard-sub-ocr.txt"
    assert captured["ocr_reference_file"] == expected_ocr
    assert f"ocr_reference: {expected_ocr}" in capsys.readouterr().out


def test_run_parser_accepts_js_runtime_choices() -> None:
    args = cli.build_parser().parse_args(
        [
            "run",
            "https://example.com/video",
            "--yt-dlp-js-runtimes",
            "bun",
        ]
    )

    assert args.yt_dlp_js_runtimes == "bun"


def test_run_parser_defaults_js_runtime_to_node() -> None:
    args = cli.build_parser().parse_args(["run", "https://example.com/video"])

    assert args.yt_dlp_js_runtimes == "node"


def test_handle_player_generates_default_html(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    video = tmp_path / "clip.mp4"
    subtitle = tmp_path / "clip.vtt"
    video.write_text("", encoding="utf-8")
    subtitle.write_text("WEBVTT\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_generate_player_page(**kwargs: object) -> PlayerResult:
        captured.update(kwargs)
        return PlayerResult(
            html_path=kwargs["html_path"],  # type: ignore[arg-type]
            video_path=kwargs["video_file"],  # type: ignore[arg-type]
            subtitle_path=kwargs["subtitle_file"],  # type: ignore[arg-type]
        )

    monkeypatch.setattr(cli, "generate_player_page", fake_generate_player_page)
    args = argparse.Namespace(
        video_file=video, subtitle_file=subtitle, output_html=None
    )

    assert cli.handle_player(args) == 0

    assert captured["html_path"] == subtitle.with_suffix(".player.html").resolve()
    assert "player:" in capsys.readouterr().out
