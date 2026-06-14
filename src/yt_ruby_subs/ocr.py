import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .errors import CliError
from .process_utils import resolve_command, run_subprocess

DEFAULT_OCR_CROP = "iw:ih*0.35:0:ih*0.65"
PADDLEOCR_VL_VERSION = "v1.6"
SUPPORTED_OCR_ENGINES = ("tesseract", "paddleocr-vl")


@dataclass(frozen=True, slots=True)
class OcrOptions:
    engine: str = "tesseract"
    language: str = "jpn"
    interval_seconds: float = 1.0
    crop: str = DEFAULT_OCR_CROP
    ffmpeg_bin: str = "ffmpeg"
    tesseract_bin: str = "tesseract"
    paddleocr_vl_device: str = ""
    paddleocr_vl_backend: str = ""
    paddleocr_vl_server_url: str = ""
    paddleocr_vl_api_model_name: str = ""
    paddleocr_vl_api_key: str = ""


class FrameRecognizer(Protocol):
    def recognize(self, frame: Path) -> str: ...


@dataclass(slots=True)
class TesseractFrameRecognizer:
    pytesseract: Any
    language: str

    def recognize(self, frame: Path) -> str:
        text = self.pytesseract.image_to_string(str(frame), lang=self.language)
        return normalize_ocr_text(text)


@dataclass(slots=True)
class PaddleOcrVlFrameRecognizer:
    pipeline: Any

    def recognize(self, frame: Path) -> str:
        with tempfile.TemporaryDirectory(
            prefix="yt-ruby-subs-paddleocr-vl-"
        ) as temp_dir_str:
            output_dir = Path(temp_dir_str)
            for result in self.pipeline.predict(str(frame)):
                result.save_to_markdown(save_path=output_dir)
            return normalize_ocr_text(read_markdown_output(output_dir))


def run_hard_subtitle_ocr(
    *, video_file: Path, output_file: Path, options: OcrOptions
) -> Path:
    validate_ocr_options(options)
    if options.interval_seconds <= 0:
        raise CliError("--ocr-interval must be greater than 0")
    if not video_file.is_file():
        raise CliError(f"video file not found for OCR: {video_file}")

    ffmpeg = resolve_command(
        options.ffmpeg_bin, windows_preferred=("ffmpeg.exe", "ffmpeg")
    )
    recognizer = build_frame_recognizer(options)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="yt-ruby-subs-ocr-") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        frame_pattern = temp_dir / "frame_%06d.png"
        extract_ocr_frames(
            ffmpeg=ffmpeg,
            video_file=video_file,
            frame_pattern=frame_pattern,
            options=options,
        )
        frames = sorted(temp_dir.glob("frame_*.png"))
        if not frames:
            raise CliError("OCR frame extraction produced no images")

        write_ocr_reference(
            output_file=output_file,
            video_file=video_file,
            frames=frames,
            options=options,
            recognizer=recognizer,
        )
    return output_file


def validate_ocr_options(options: OcrOptions) -> None:
    if options.engine not in SUPPORTED_OCR_ENGINES:
        supported = ", ".join(SUPPORTED_OCR_ENGINES)
        raise CliError(
            f"unsupported OCR engine: {options.engine}; choose one of: {supported}"
        )


def build_frame_recognizer(options: OcrOptions) -> FrameRecognizer:
    if options.engine == "tesseract":
        tesseract = resolve_command(
            options.tesseract_bin,
            windows_preferred=("tesseract.exe", "tesseract"),
        )
        pytesseract = load_tesseract_dependency()
        pytesseract.pytesseract.tesseract_cmd = tesseract
        return TesseractFrameRecognizer(
            pytesseract=pytesseract, language=options.language
        )

    if options.engine == "paddleocr-vl":
        return PaddleOcrVlFrameRecognizer(
            pipeline=create_paddleocr_vl_pipeline(options)
        )

    raise AssertionError(f"unvalidated OCR engine: {options.engine}")


def load_tesseract_dependency() -> Any:
    try:
        import pytesseract  # type: ignore[import-not-found]
    except ImportError as exc:
        raise CliError(
            "OCR dependencies are not installed; install this project with the OCR extra, "
            'for example: uv pip install -e ".[ocr]"'
        ) from exc
    return pytesseract


def create_paddleocr_vl_pipeline(options: OcrOptions) -> Any:
    try:
        from paddleocr import PaddleOCRVL  # type: ignore[import-not-found]
    except ImportError as exc:
        raise CliError(
            "PaddleOCR-VL dependencies are not installed; install this project with the "
            'PaddleOCR-VL extra, for example: uv pip install -e ".[paddleocr-vl]"'
        ) from exc

    # Official PaddleOCR-VL docs expose PaddleOCRVL, pipeline_version="v1.6",
    # and save_to_markdown output:
    # https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/PaddleOCR-VL.html
    kwargs = compact_options(
        {
            "pipeline_version": PADDLEOCR_VL_VERSION,
            "device": options.paddleocr_vl_device,
            "vl_rec_backend": options.paddleocr_vl_backend,
            "vl_rec_server_url": options.paddleocr_vl_server_url,
            "vl_rec_api_model_name": options.paddleocr_vl_api_model_name,
            "vl_rec_api_key": options.paddleocr_vl_api_key,
        }
    )
    return PaddleOCRVL(**kwargs)


def compact_options(values: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in values.items() if value}


def extract_ocr_frames(
    *, ffmpeg: str, video_file: Path, frame_pattern: Path, options: OcrOptions
) -> None:
    filters = [f"fps=1/{options.interval_seconds:g}"]
    if options.crop:
        filters.insert(0, f"crop={options.crop}")
    run_subprocess(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_file),
            "-vf",
            ",".join(filters),
            str(frame_pattern),
        ],
        cwd=video_file.parent,
    )


def write_ocr_reference(
    *,
    output_file: Path,
    video_file: Path,
    frames: list[Path],
    options: OcrOptions,
    recognizer: FrameRecognizer,
) -> None:
    lines = [
        "# Hard subtitle OCR reference",
        f"# video: {video_file.name}",
        f"# engine: {options.engine}",
        f"# language: {options.language}",
        f"# interval_seconds: {options.interval_seconds:g}",
        f"# crop: {options.crop}",
        "",
    ]
    previous_text = ""
    for frame in frames:
        text = recognizer.recognize(frame)
        if not text or text == previous_text:
            continue
        lines.extend([f"[{frame.stem}]", text, ""])
        previous_text = text

    if previous_text == "":
        lines.append("# no OCR text detected")

    output_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def read_markdown_output(output_dir: Path) -> str:
    parts = [
        path.read_text(encoding="utf-8-sig") for path in sorted(output_dir.glob("*.md"))
    ]
    return "\n".join(parts)


def normalize_ocr_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
