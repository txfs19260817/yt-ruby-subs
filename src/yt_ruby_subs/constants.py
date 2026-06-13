from typing import Any

SUBTITLE_EXTENSIONS = {".vtt", ".srt", ".ass", ".ssa", ".ttml", ".srv3", ".json3"}

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
