from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class DownloadResult:
    work_dir: Path
    video_files: list[Path]
    subtitle_files: list[Path]
    selected_subtitle: Path | None
    info_files: list[Path]


@dataclass(slots=True)
class GenerationResult:
    corrected_subtitle_path: Path
    webvtt_path: Path
    provider: str
    summary: str | None
    player_path: Path | None


@dataclass(slots=True)
class PlayerResult:
    html_path: Path
    video_path: Path | None
    subtitle_path: Path
