from typing import Any, Literal

DEFAULT_API_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODELS = {
    "codex": "gpt-5.5",
    "claude": "best",
    "api": "",
}
GENERATION_PROVIDERS = ("codex", "claude", "api")

DEFAULT_OCR_BOTTOM_RATIO = 0.15
DEFAULT_OCR_WIDTH_RATIO = 0.8
DEFAULT_OCR_CROP = (
    f"iw*{DEFAULT_OCR_WIDTH_RATIO:g}:ih*{DEFAULT_OCR_BOTTOM_RATIO:g}:"
    f"iw*{(1 - DEFAULT_OCR_WIDTH_RATIO) / 2:g}:"
    f"ih*{1 - DEFAULT_OCR_BOTTOM_RATIO:g}"
)
DEFAULT_OCR_FRAME_DEDUPE = True
DEFAULT_OCR_INTERVAL_SECONDS = 1.5
DEFAULT_OCR_TEMP_DIR = "system"
DEFAULT_PADDLEOCR_VL_DEVICE = "gpu"
DEFAULT_PPOCRV6_DEVICE = "gpu:0"
DEFAULT_PPOCRV6_MODEL = "small"
OCR_TEMP_DIR_MODES = ("system", "output")
PADDLEOCR_VL_VERSION = "v1.6"
PPOCRV6_LANGUAGE_ALIASES = {
    "ja": "japan",
    "jp": "japan",
    "jpn": "japan",
}
PPOCRV6_MODEL_NAMES: dict[str, dict[str, str]] = {
    "tiny": {
        "detection": "PP-OCRv6_tiny_det",
        "recognition": "PP-OCRv6_tiny_rec",
    },
    "small": {
        "detection": "PP-OCRv6_small_det",
        "recognition": "PP-OCRv6_small_rec",
    },
    "medium": {
        "detection": "PP-OCRv6_medium_det",
        "recognition": "PP-OCRv6_medium_rec",
    },
}
PPOCRV6_MODELS = tuple(PPOCRV6_MODEL_NAMES)
SUPPORTED_OCR_ENGINES = ("tesseract", "paddleocr-vl", "ppocrv6")
type OcrTempDirMode = Literal["system", "output"]
type PpOcrV6Model = Literal["tiny", "small", "medium"]

SUBTITLE_EXTENSIONS = {".vtt", ".srt", ".ass", ".ssa", ".ttml", ".srv3", ".json3"}

DEFAULT_YT_DLP_JS_RUNTIME = "node"
YT_DLP_JS_RUNTIMES = ("deno", "node", "bun", "quickjs")
type YtDlpJsRuntime = Literal["deno", "node", "bun", "quickjs"]

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".webm",
    ".m4v",
    ".mov",
    ".avi",
    ".flv",
    ".ts",
    ".m2ts",
}

CORRECTED_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "corrected_vtt": {"type": "string", "minLength": 1},
    },
    "required": ["corrected_vtt"],
}

RUBY_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "webvtt": {"type": "string", "minLength": 1},
    },
    "required": ["webvtt"],
}

SUMMARY_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
    },
    "required": ["summary"],
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        **CORRECTED_OUTPUT_SCHEMA["properties"],
        **RUBY_OUTPUT_SCHEMA["properties"],
        **SUMMARY_OUTPUT_SCHEMA["properties"],
    },
    "required": ["corrected_vtt", "webvtt", "summary"],
}
