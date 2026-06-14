import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from yt_ruby_subs import ocr
from yt_ruby_subs.errors import CliError


def test_run_hard_subtitle_ocr_extracts_frames_and_writes_text(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_text("video", encoding="utf-8")
    output = tmp_path / "clip.hard-sub-ocr.txt"
    commands: list[list[str]] = []

    monkeypatch.setattr(ocr, "resolve_command", lambda raw, *, windows_preferred: raw)

    def fake_run_subprocess(
        command: list[str],
        *,
        cwd: Path,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        assert cwd == video.parent
        commands.append(command)
        frame_pattern = Path(command[-1])
        frame_pattern.parent.mkdir(parents=True, exist_ok=True)
        (frame_pattern.parent / "frame_000001.png").write_text(
            "frame", encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    class FakePytesseract:
        class pytesseract:
            tesseract_cmd = ""

        @staticmethod
        def image_to_string(path: str, *, lang: str) -> str:
            assert path.endswith("frame_000001.png")
            assert lang == "jpn"
            return "昇龍拳\n"

    monkeypatch.setattr(ocr, "run_subprocess", fake_run_subprocess)
    monkeypatch.setattr(ocr, "load_tesseract_dependency", lambda: FakePytesseract)

    result = ocr.run_hard_subtitle_ocr(
        video_file=video,
        output_file=output,
        options=ocr.OcrOptions(language="jpn", interval_seconds=0.5),
    )

    assert result == output
    assert "昇龍拳" in output.read_text(encoding="utf-8")
    assert commands[0][0] == "ffmpeg"
    assert any("fps=1/0.5" in part for part in commands[0])
    assert FakePytesseract.pytesseract.tesseract_cmd == "tesseract"


def test_run_hard_subtitle_ocr_supports_paddleocr_vl(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_text("video", encoding="utf-8")
    output = tmp_path / "clip.hard-sub-ocr.txt"
    created_options: list[ocr.OcrOptions] = []

    monkeypatch.setattr(ocr, "resolve_command", lambda raw, *, windows_preferred: raw)

    def fake_run_subprocess(
        command: list[str],
        *,
        cwd: Path,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        frame_pattern = Path(command[-1])
        frame_pattern.parent.mkdir(parents=True, exist_ok=True)
        (frame_pattern.parent / "frame_000001.png").write_text(
            "frame", encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    @dataclass(slots=True)
    class FakeResult:
        text: str

        def save_to_markdown(self, *, save_path: Path) -> None:
            (save_path / "frame_000001.md").write_text(self.text, encoding="utf-8")

    class FakePipeline:
        def predict(self, image: str) -> list[FakeResult]:
            assert image.endswith("frame_000001.png")
            return [FakeResult("波動拳\n")]

    def fake_create_paddleocr_vl_pipeline(options: ocr.OcrOptions) -> FakePipeline:
        created_options.append(options)
        return FakePipeline()

    monkeypatch.setattr(ocr, "run_subprocess", fake_run_subprocess)
    monkeypatch.setattr(
        ocr, "create_paddleocr_vl_pipeline", fake_create_paddleocr_vl_pipeline
    )

    result = ocr.run_hard_subtitle_ocr(
        video_file=video,
        output_file=output,
        options=ocr.OcrOptions(
            engine="paddleocr-vl",
            paddleocr_vl_device="gpu",
            paddleocr_vl_backend="vllm-server",
            paddleocr_vl_server_url="http://localhost:8000/v1",
        ),
    )

    text = output.read_text(encoding="utf-8")
    assert result == output
    assert "# engine: paddleocr-vl" in text
    assert "波動拳" in text
    assert created_options[0].paddleocr_vl_device == "gpu"
    assert created_options[0].paddleocr_vl_backend == "vllm-server"


def test_paddleocr_vl_rejects_cpu_device() -> None:
    options = ocr.OcrOptions(engine="paddleocr-vl", paddleocr_vl_device="cpu")

    with pytest.raises(CliError, match="GPU-only"):
        ocr.validate_ocr_options(options)
