import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .errors import CliError
from .process_utils import resolve_command, run_subprocess

DEFAULT_OCR_BOTTOM_RATIO = 0.2
DEFAULT_OCR_CROP = (
    f"iw:ih*{DEFAULT_OCR_BOTTOM_RATIO:g}:0:ih*{1 - DEFAULT_OCR_BOTTOM_RATIO:g}"
)
DEFAULT_OCR_FRAME_DEDUPE = True
DEFAULT_PADDLEOCR_VL_DEVICE = "gpu"
PADDLEOCR_VL_VERSION = "v1.6"
SUPPORTED_OCR_ENGINES = ("tesseract", "paddleocr-vl")
_DLL_DIRECTORY_HANDLES: list[Any] = []


@dataclass(frozen=True, slots=True)
class OcrOptions:
    engine: str = "tesseract"
    language: str = "jpn"
    interval_seconds: float = 1.0
    bottom_ratio: float = DEFAULT_OCR_BOTTOM_RATIO
    crop: str = ""
    frame_dedupe: bool = DEFAULT_OCR_FRAME_DEDUPE
    ffmpeg_bin: str = "ffmpeg"
    tesseract_bin: str = "tesseract"
    paddleocr_vl_device: str = DEFAULT_PADDLEOCR_VL_DEVICE
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
    if not 0 < options.bottom_ratio <= 1:
        raise CliError("--ocr-bottom-ratio must be greater than 0 and at most 1")
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
    if (
        options.engine == "paddleocr-vl"
        and not options.paddleocr_vl_device.lower().startswith("gpu")
    ):
        raise CliError(
            "PaddleOCR-VL OCR is GPU-only in this project; use --paddleocr-vl-device gpu "
            "and install the paddleocr-vl extra with paddlepaddle-gpu"
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
    ensure_paddle_gpu_available()
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


def ensure_paddle_gpu_available() -> None:
    configure_nvidia_dll_path()
    try:
        import paddle  # type: ignore[import-not-found]
    except ImportError as exc:
        raise CliError(
            "PaddleOCR-VL OCR is GPU-only in this project, but PaddlePaddle is not installed; "
            "install with: uv sync --extra paddleocr-vl"
        ) from exc

    # Official Paddle APIs expose whether a wheel supports CUDA and how many GPUs are visible:
    # https://www.paddlepaddle.org.cn/documentation/docs/en/api/paddle/device/is_compiled_with_cuda_en.html
    # https://www.paddlepaddle.org.cn/documentation/docs/en/api/paddle/device/cuda/device_count_en.html
    if not paddle.device.is_compiled_with_cuda():
        raise CliError(
            "PaddleOCR-VL OCR is GPU-only in this project, but the installed PaddlePaddle "
            "wheel is CPU-only; install paddlepaddle-gpu from Paddle's CUDA package index"
        )
    if paddle.device.cuda.device_count() <= 0:
        raise CliError(
            "PaddleOCR-VL OCR is GPU-only in this project, but PaddlePaddle cannot see a GPU"
        )


def configure_nvidia_dll_path() -> None:
    if os.name != "nt":
        return

    for directory in find_nvidia_dll_directories(
        [Path(item) for item in sys.path if item]
    ):
        prepend_process_path(directory)
        if hasattr(os, "add_dll_directory"):
            _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(directory)))


def find_nvidia_dll_directories(roots: list[Path]) -> list[Path]:
    directories: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        nvidia_dir = root / "nvidia"
        if not nvidia_dir.is_dir():
            continue
        for dll_path in sorted(nvidia_dir.rglob("*.dll")):
            directory = dll_path.parent.resolve()
            key = str(directory).casefold()
            if key not in seen:
                directories.append(directory)
                seen.add(key)
    return directories


def prepend_process_path(directory: Path) -> None:
    directory_text = str(directory)
    current = os.environ.get("PATH", "")
    existing = {item.casefold() for item in current.split(os.pathsep) if item}
    if directory_text.casefold() not in existing:
        os.environ["PATH"] = directory_text + os.pathsep + current


def compact_options(values: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in values.items() if value}


def extract_ocr_frames(
    *, ffmpeg: str, video_file: Path, frame_pattern: Path, options: OcrOptions
) -> None:
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
            ",".join(build_ocr_video_filters(options)),
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
        f"# bottom_ratio: {options.bottom_ratio:g}",
        f"# crop: {resolve_ocr_crop(options)}",
        f"# frame_dedupe: {str(options.frame_dedupe).lower()}",
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


def resolve_ocr_crop(options: OcrOptions) -> str:
    return options.crop or build_bottom_crop(options.bottom_ratio)


def build_ocr_video_filters(options: OcrOptions) -> list[str]:
    filters = [
        f"crop={resolve_ocr_crop(options)}",
        f"fps=1/{options.interval_seconds:g}",
    ]
    if options.frame_dedupe:
        filters.append("mpdecimate")
    return filters


def build_bottom_crop(ratio: float) -> str:
    if not 0 < ratio <= 1:
        raise CliError("--ocr-bottom-ratio must be greater than 0 and at most 1")
    return f"iw:ih*{ratio:g}:0:ih*{1 - ratio:g}"


def normalize_ocr_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
