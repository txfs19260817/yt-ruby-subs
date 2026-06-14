import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
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
        options=ocr.OcrOptions(
            language="jpn",
            interval_seconds=0.5,
            bottom_ratio=0.2,
        ),
    )

    assert result == output
    text = output.read_text(encoding="utf-8")
    assert "昇龍拳" in text
    assert "# bottom_ratio: 0.2" in text
    assert "# width_ratio: 0.8" in text
    assert "# crop: iw*0.8:ih*0.2:iw*0.1:ih*0.8" in text
    assert "# frame_dedupe: true" in text
    assert commands[0][0] == "ffmpeg"
    assert any("fps=1/0.5" in part for part in commands[0])
    assert any("crop=iw*0.8:ih*0.2:iw*0.1:ih*0.8" in part for part in commands[0])
    assert any("mpdecimate" in part for part in commands[0])
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


def test_run_hard_subtitle_ocr_supports_ppocrv6(
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
        json: dict[str, object]

    class FakePipeline:
        def predict(self, image: str) -> list[FakeResult]:
            assert image.endswith("frame_000001.png")
            return [
                FakeResult(
                    {
                        "res": {
                            "rec_texts": ["昇龍拳", "", "波動拳"],
                        }
                    }
                )
            ]

    def fake_create_ppocrv6_pipeline(options: ocr.OcrOptions) -> FakePipeline:
        created_options.append(options)
        return FakePipeline()

    monkeypatch.setattr(ocr, "run_subprocess", fake_run_subprocess)
    monkeypatch.setattr(ocr, "create_ppocrv6_pipeline", fake_create_ppocrv6_pipeline)

    result = ocr.run_hard_subtitle_ocr(
        video_file=video,
        output_file=output,
        options=ocr.OcrOptions(
            engine="ppocrv6",
            ppocrv6_model="small",
            ppocrv6_device="gpu:0",
        ),
    )

    text = output.read_text(encoding="utf-8")
    assert result == output
    assert "# engine: ppocrv6" in text
    assert "# ppocrv6_model: small" in text
    assert "# ppocrv6_device: gpu:0" in text
    assert "# ppocrv6_lang: japan" in text
    assert "昇龍拳\n波動拳" in text
    assert created_options[0].ppocrv6_model == "small"
    assert created_options[0].ppocrv6_device == "gpu:0"


def test_run_hard_subtitle_ocr_can_place_temp_dir_under_output(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_text("video", encoding="utf-8")
    output_dir = tmp_path / "output"
    output = output_dir / "clip.hard-sub-ocr.txt"
    frame_dirs: list[Path] = []

    monkeypatch.setattr(ocr, "resolve_command", lambda raw, *, windows_preferred: raw)
    monkeypatch.setattr(
        ocr,
        "build_frame_recognizer",
        lambda options: ocr.TesseractFrameRecognizer(
            pytesseract=SimpleNamespace(
                pytesseract=SimpleNamespace(tesseract_cmd=""),
                image_to_string=lambda path, *, lang: "字幕",
            ),
            language="jpn",
        ),
    )

    def fake_run_subprocess(
        command: list[str],
        *,
        cwd: Path,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        frame_pattern = Path(command[-1])
        frame_dirs.append(frame_pattern.parent)
        assert frame_pattern.parent.parent == output_dir
        frame_pattern.parent.mkdir(parents=True, exist_ok=True)
        (frame_pattern.parent / "frame_000001.png").write_text(
            "frame", encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(ocr, "run_subprocess", fake_run_subprocess)

    ocr.run_hard_subtitle_ocr(
        video_file=video,
        output_file=output,
        options=ocr.OcrOptions(temp_dir="output"),
    )

    assert frame_dirs
    assert output.is_file()


def test_write_ocr_reference_skips_missing_frames(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_text("video", encoding="utf-8")
    present_frame = tmp_path / "frame_000001.png"
    missing_frame = tmp_path / "frame_000002.png"
    output = tmp_path / "clip.hard-sub-ocr.txt"
    present_frame.write_text("frame", encoding="utf-8")
    recognized: list[Path] = []

    class FakeRecognizer:
        def recognize(self, frame: Path) -> str:
            recognized.append(frame)
            return "残ったフレーム"

    caplog.set_level(logging.INFO, logger="yt_ruby_subs.ocr")

    ocr.write_ocr_reference(
        output_file=output,
        video_file=video,
        frames=[present_frame, missing_frame],
        options=ocr.OcrOptions(),
        recognizer=FakeRecognizer(),
    )

    assert recognized == [present_frame]
    assert "残ったフレーム" in output.read_text(encoding="utf-8")
    messages = [record.getMessage() for record in caplog.records]
    assert "ocr_frame: 1/2 frame_000001.png" in messages
    assert "OCR frame skipped because it no longer exists: frame_000002.png" in messages


def test_paddleocr_vl_rejects_cpu_device() -> None:
    options = ocr.OcrOptions(engine="paddleocr-vl", paddleocr_vl_device="cpu")

    with pytest.raises(CliError, match="GPU-only"):
        ocr.validate_ocr_options(options)


def test_ppocrv6_rejects_cpu_device() -> None:
    options = ocr.OcrOptions(engine="ppocrv6", ppocrv6_device="cpu")

    with pytest.raises(CliError, match="GPU-only"):
        ocr.validate_ocr_options(options)


def test_ppocrv6_rejects_unknown_model_size() -> None:
    options = ocr.OcrOptions(engine="ppocrv6", ppocrv6_model="large")

    with pytest.raises(CliError, match="ppocrv6-model"):
        ocr.validate_ocr_options(options)


def test_ppocrv6_rejects_tiny_for_japanese() -> None:
    options = ocr.OcrOptions(engine="ppocrv6", ppocrv6_model="tiny", language="jpn")

    with pytest.raises(CliError, match="does not support Japanese"):
        ocr.validate_ocr_options(options)


def test_create_ppocrv6_pipeline_uses_selected_model_and_gpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    fake_paddleocr = ModuleType("paddleocr")

    class FakePaddleOCR:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    fake_paddleocr.PaddleOCR = FakePaddleOCR
    monkeypatch.setitem(ocr.sys.modules, "paddleocr", fake_paddleocr)
    monkeypatch.setattr(ocr, "ensure_paddle_gpu_available", lambda *args: None)

    pipeline = ocr.create_ppocrv6_pipeline(
        ocr.OcrOptions(
            engine="ppocrv6",
            ppocrv6_model="small",
            ppocrv6_device="gpu:1",
            language="jpn",
        )
    )

    assert isinstance(pipeline, FakePaddleOCR)
    assert captured["ocr_version"] == "PP-OCRv6"
    assert captured["lang"] == "japan"
    assert captured["device"] == "gpu:1"
    assert captured["text_detection_model_name"] == "PP-OCRv6_small_det"
    assert captured["text_recognition_model_name"] == "PP-OCRv6_small_rec"
    assert captured["use_doc_orientation_classify"] is False
    assert captured["use_doc_unwarping"] is False
    assert captured["use_textline_orientation"] is False


def test_release_frame_recognizer_clears_paddle_pipeline_and_cuda_cache(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []
    recognizer = ocr.PaddleOcrVlFrameRecognizer(pipeline=object())
    fake_paddle = SimpleNamespace(
        device=SimpleNamespace(
            cuda=SimpleNamespace(empty_cache=lambda: calls.append("empty_cache"))
        )
    )
    monkeypatch.setitem(ocr.sys.modules, "paddle", fake_paddle)
    caplog.set_level(logging.INFO, logger="yt_ruby_subs.ocr")

    ocr.release_frame_recognizer(recognizer)

    assert recognizer.pipeline is None
    assert calls == ["empty_cache"]
    assert "paddle_cuda_cache_released" in [
        record.getMessage() for record in caplog.records
    ]


def test_build_subtitle_crop_and_explicit_override() -> None:
    assert ocr.build_subtitle_crop(0.2, 0.8) == "iw*0.8:ih*0.2:iw*0.1:ih*0.8"
    assert (
        ocr.resolve_ocr_crop(ocr.OcrOptions(bottom_ratio=0.25, width_ratio=0.5))
        == "iw*0.5:ih*0.25:iw*0.25:ih*0.75"
    )
    assert (
        ocr.resolve_ocr_crop(ocr.OcrOptions(crop="iw:100:0:ih-100"))
        == "iw:100:0:ih-100"
    )


def test_build_ocr_video_filters_deduplicates_frames_by_default() -> None:
    assert ocr.build_ocr_video_filters(
        ocr.OcrOptions(interval_seconds=2, bottom_ratio=0.2)
    ) == [
        "crop=iw*0.8:ih*0.2:iw*0.1:ih*0.8",
        "fps=1/2",
        "mpdecimate",
    ]


def test_build_ocr_video_filters_can_disable_frame_dedupe() -> None:
    assert ocr.build_ocr_video_filters(
        ocr.OcrOptions(interval_seconds=1, bottom_ratio=0.2, frame_dedupe=False)
    ) == [
        "crop=iw*0.8:ih*0.2:iw*0.1:ih*0.8",
        "fps=1/1",
    ]


def test_build_subtitle_crop_rejects_invalid_ratios() -> None:
    with pytest.raises(CliError, match="ocr-bottom-ratio"):
        ocr.build_subtitle_crop(0, 0.8)
    with pytest.raises(CliError, match="ocr-width-ratio"):
        ocr.build_subtitle_crop(0.2, 0)


def test_find_nvidia_dll_directories(tmp_path: Path) -> None:
    dll_dir = tmp_path / "site-packages" / "nvidia" / "cudnn" / "bin"
    dll_dir.mkdir(parents=True)
    (dll_dir / "cudnn64_9.dll").write_text("", encoding="utf-8")

    assert ocr.find_nvidia_dll_directories([tmp_path / "site-packages"]) == [
        dll_dir.resolve()
    ]


def test_prepend_process_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    monkeypatch.setenv("PATH", str(second))

    ocr.prepend_process_path(first)
    ocr.prepend_process_path(first)

    assert ocr.os.environ["PATH"].split(ocr.os.pathsep) == [str(first), str(second)]
