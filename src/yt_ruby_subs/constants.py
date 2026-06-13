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

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "corrected_vtt": {"type": "string", "minLength": 1},
        "webvtt": {"type": "string", "minLength": 1},
        "summary": {"type": "string"},
    },
    "required": ["corrected_vtt", "webvtt", "summary"],
}
