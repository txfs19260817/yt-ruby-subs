import gc
import logging
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .constants import (
    DEFAULT_OCR_BOTTOM_RATIO,
    DEFAULT_OCR_FRAME_DEDUPE,
    DEFAULT_OCR_INTERVAL_SECONDS,
    DEFAULT_OCR_TEMP_DIR,
    DEFAULT_OCR_WIDTH_RATIO,
    DEFAULT_PADDLEOCR_VL_DEVICE,
    DEFAULT_PPOCRV6_DEVICE,
    DEFAULT_PPOCRV6_MODEL,
    OCR_TEMP_DIR_MODES,
    PADDLEOCR_VL_VERSION,
    PPOCRV6_MODEL_NAMES,
    PPOCRV6_MODELS,
    SUPPORTED_OCR_ENGINES,
    OcrTempDirMode,
)
from .errors import CliError
from .process_utils import resolve_command, run_subprocess

_DLL_DIRECTORY_HANDLES: list[Any] = []
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OcrOptions:
    engine: str = "tesseract"
    language: str = "jpn"
    interval_seconds: float = DEFAULT_OCR_INTERVAL_SECONDS
    bottom_ratio: float = DEFAULT_OCR_BOTTOM_RATIO
    width_ratio: float = DEFAULT_OCR_WIDTH_RATIO
    crop: str = ""
    frame_dedupe: bool = DEFAULT_OCR_FRAME_DEDUPE
    ffmpeg_bin: str = "ffmpeg"
    tesseract_bin: str = "tesseract"
    paddleocr_vl_device: str = DEFAULT_PADDLEOCR_VL_DEVICE
    paddleocr_vl_backend: str = ""
    paddleocr_vl_server_url: str = ""
    paddleocr_vl_api_model_name: str = ""
    paddleocr_vl_api_key: str = ""
    ppocrv6_model: str = DEFAULT_PPOCRV6_MODEL
    ppocrv6_device: str = DEFAULT_PPOCRV6_DEVICE
    temp_dir: OcrTempDirMode = DEFAULT_OCR_TEMP_DIR


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


@dataclass(slots=True)
class PpOcrV6FrameRecognizer:
    pipeline: Any

    def recognize(self, frame: Path) -> str:
        texts: list[str] = []
        for result in self.pipeline.predict(str(frame)):
            texts.extend(extract_ppocrv6_texts(result))
        return normalize_ocr_text("\n".join(texts))


def run_hard_subtitle_ocr(
    *, video_file: Path, output_file: Path, options: OcrOptions
) -> Path:
    validate_ocr_options(options)
    if options.interval_seconds <= 0:
        raise CliError("--ocr-interval must be greater than 0")
    if not 0 < options.bottom_ratio <= 1:
        raise CliError("--ocr-bottom-ratio must be greater than 0 and at most 1")
    if not 0 < options.width_ratio <= 1:
        raise CliError("--ocr-width-ratio must be greater than 0 and at most 1")
    if not video_file.is_file():
        raise CliError(f"video file not found for OCR: {video_file}")

    ffmpeg = resolve_command(
        options.ffmpeg_bin, windows_preferred=("ffmpeg.exe", "ffmpeg")
    )
    recognizer = build_frame_recognizer(options)

    try:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        temp_parent = resolve_ocr_temp_parent(output_file, options)
        with tempfile.TemporaryDirectory(
            prefix="yt-ruby-subs-ocr-",
            dir=temp_parent,
        ) as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            logger.info("ocr_temp_dir: %s", temp_dir)
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
    finally:
        release_frame_recognizer(recognizer)
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
    if (
        options.engine == "ppocrv6"
        and not options.ppocrv6_device.lower().startswith("gpu")
    ):
        raise CliError(
            "PP-OCRv6 OCR is GPU-only in this project; use --ppocrv6-device gpu:0 "
            "and install the ppocrv6 extra with paddlepaddle-gpu"
        )
    if options.engine == "ppocrv6" and options.ppocrv6_model not in PPOCRV6_MODELS:
        supported = ", ".join(PPOCRV6_MODELS)
        raise CliError(
            f"unsupported --ppocrv6-model: {options.ppocrv6_model}; choose one of: {supported}"
        )
    if options.temp_dir not in OCR_TEMP_DIR_MODES:
        supported = ", ".join(OCR_TEMP_DIR_MODES)
        raise CliError(
            f"unsupported OCR temp dir mode: {options.temp_dir}; choose one of: {supported}"
        )


def resolve_ocr_temp_parent(output_file: Path, options: OcrOptions) -> Path | None:
    if options.temp_dir == "system":
        return None
    if options.temp_dir == "output":
        return output_file.parent
    raise AssertionError(f"unvalidated OCR temp dir mode: {options.temp_dir}")


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
    if options.engine == "ppocrv6":
        return PpOcrV6FrameRecognizer(pipeline=create_ppocrv6_pipeline(options))

    raise AssertionError(f"unvalidated OCR engine: {options.engine}")


def release_frame_recognizer(recognizer: FrameRecognizer) -> None:
    if isinstance(recognizer, PaddleOcrVlFrameRecognizer | PpOcrV6FrameRecognizer):
        recognizer.pipeline = None
    gc.collect()
    release_paddle_cuda_cache()


def release_paddle_cuda_cache() -> None:
    paddle = sys.modules.get("paddle")
    if paddle is None:
        return

    empty_cache = getattr(
        getattr(getattr(paddle, "device", None), "cuda", None),
        "empty_cache",
        None,
    )
    if callable(empty_cache):
        try:
            empty_cache()
        except Exception:
            logger.debug("failed to release Paddle CUDA cache", exc_info=True)
        else:
            logger.info("paddle_cuda_cache_released")


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
    ensure_paddle_gpu_available("PaddleOCR-VL")
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


def create_ppocrv6_pipeline(options: OcrOptions) -> Any:
    ensure_paddle_gpu_available("PP-OCRv6")
    try:
        from paddleocr import PaddleOCR  # type: ignore[import-not-found]
    except ImportError as exc:
        raise CliError(
            "PP-OCRv6 dependencies are not installed; install this project with the "
            'PP-OCRv6 extra, for example: uv pip install -e ".[ppocrv6]"'
        ) from exc

    try:
        model_names = PPOCRV6_MODEL_NAMES[options.ppocrv6_model]
    except KeyError as exc:
        supported = ", ".join(PPOCRV6_MODELS)
        raise CliError(
            f"unsupported --ppocrv6-model: {options.ppocrv6_model}; choose one of: {supported}"
        ) from exc

    # Official OCR pipeline docs expose PaddleOCR, ocr_version, device, and
    # text_detection_model_name/text_recognition_model_name.
    # https://www.paddleocr.ai/main/version3.x/pipeline_usage/OCR.html
    return PaddleOCR(
        ocr_version="PP-OCRv6",
        device=options.ppocrv6_device,
        text_detection_model_name=model_names["detection"],
        text_recognition_model_name=model_names["recognition"],
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


def ensure_paddle_gpu_available(engine_name: str = "Paddle OCR") -> None:
    configure_nvidia_dll_path()
    try:
        import paddle  # type: ignore[import-not-found]
    except ImportError as exc:
        raise CliError(
            f"{engine_name} OCR is GPU-only in this project, but PaddlePaddle is not installed; "
            "install with the matching Paddle OCR extra"
        ) from exc

    # Official Paddle APIs expose whether a wheel supports CUDA and how many GPUs are visible:
    # https://www.paddlepaddle.org.cn/documentation/docs/en/api/paddle/device/is_compiled_with_cuda_en.html
    # https://www.paddlepaddle.org.cn/documentation/docs/en/api/paddle/device/cuda/device_count_en.html
    if not paddle.device.is_compiled_with_cuda():
        raise CliError(
            f"{engine_name} OCR is GPU-only in this project, but the installed PaddlePaddle "
            "wheel is CPU-only; install paddlepaddle-gpu from Paddle's CUDA package index"
        )
    if paddle.device.cuda.device_count() <= 0:
        raise CliError(
            f"{engine_name} OCR is GPU-only in this project, but PaddlePaddle cannot see a GPU"
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
        *build_ocr_engine_header(options),
        f"# language: {options.language}",
        f"# interval_seconds: {options.interval_seconds:g}",
        f"# bottom_ratio: {options.bottom_ratio:g}",
        f"# width_ratio: {options.width_ratio:g}",
        f"# crop: {resolve_ocr_crop(options)}",
        f"# frame_dedupe: {str(options.frame_dedupe).lower()}",
        "",
    ]
    previous_text = ""
    total_frames = len(frames)
    for index, frame in enumerate(frames, start=1):
        logger.info("ocr_frame: %s/%s %s", index, total_frames, frame.name)
        if not frame.exists():
            logger.warning(
                "OCR frame skipped because it no longer exists: %s",
                frame.name,
            )
            continue
        text = recognizer.recognize(frame)
        if not text or text == previous_text:
            continue
        lines.extend([f"[{frame.stem}]", text, ""])
        previous_text = text

    if previous_text == "":
        lines.append("# no OCR text detected")

    output_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def build_ocr_engine_header(options: OcrOptions) -> list[str]:
    if options.engine == "ppocrv6":
        return [
            f"# ppocrv6_model: {options.ppocrv6_model}",
            f"# ppocrv6_device: {options.ppocrv6_device}",
        ]
    return []


def extract_ppocrv6_texts(result: Any) -> list[str]:
    return collect_rec_texts(extract_ppocrv6_payload(result))


def extract_ppocrv6_payload(result: Any) -> Any:
    if isinstance(result, dict):
        return result

    json_value = getattr(result, "json", None)
    if callable(json_value):
        return json_value()
    if json_value is not None:
        return json_value

    res_value = getattr(result, "res", None)
    if res_value is not None:
        return {"res": res_value}

    return result


def collect_rec_texts(value: Any) -> list[str]:
    if isinstance(value, dict):
        rec_texts = value.get("rec_texts")
        if rec_texts is not None:
            return [str(item) for item in rec_texts if str(item).strip()]

        texts: list[str] = []
        for item in value.values():
            texts.extend(collect_rec_texts(item))
        return texts

    if isinstance(value, list | tuple):
        texts: list[str] = []
        for item in value:
            texts.extend(collect_rec_texts(item))
        return texts

    return []


def read_markdown_output(output_dir: Path) -> str:
    parts = [
        path.read_text(encoding="utf-8-sig") for path in sorted(output_dir.glob("*.md"))
    ]
    return "\n".join(parts)


def resolve_ocr_crop(options: OcrOptions) -> str:
    return options.crop or build_subtitle_crop(
        options.bottom_ratio, options.width_ratio
    )


def build_ocr_video_filters(options: OcrOptions) -> list[str]:
    filters = [
        f"crop={resolve_ocr_crop(options)}",
        f"fps=1/{options.interval_seconds:g}",
    ]
    if options.frame_dedupe:
        filters.append("mpdecimate")
    return filters


def build_subtitle_crop(bottom_ratio: float, width_ratio: float) -> str:
    if not 0 < bottom_ratio <= 1:
        raise CliError("--ocr-bottom-ratio must be greater than 0 and at most 1")
    if not 0 < width_ratio <= 1:
        raise CliError("--ocr-width-ratio must be greater than 0 and at most 1")
    x_ratio = (1 - width_ratio) / 2
    y_ratio = 1 - bottom_ratio
    return f"iw*{width_ratio:g}:ih*{bottom_ratio:g}:iw*{x_ratio:g}:ih*{y_ratio:g}"


def normalize_ocr_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
