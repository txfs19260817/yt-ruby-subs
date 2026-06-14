import json
import re
from datetime import datetime
from pathlib import Path

from .constants import SUBTITLE_EXTENSIONS, VIDEO_EXTENSIONS, YtDlpJsRuntime
from .models import DownloadResult
from .process_utils import resolve_command, run_subprocess

SUBTITLE_EXTENSION_SCORES = {
    ".vtt": 40,
    ".srt": 30,
    ".ass": 20,
}


def download_with_yt_dlp(
    *,
    url: str,
    lang: str,
    output_root: Path,
    job_name: str,
    no_video: bool,
    subtitle_format: str,
    yt_dlp_bin: str,
    yt_dlp_js_runtimes: YtDlpJsRuntime,
) -> DownloadResult:
    yt_dlp = resolve_command(yt_dlp_bin, windows_preferred=("yt-dlp.exe", "yt-dlp"))
    root = output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dir_name = f"__tmp__{timestamp}"
    work_dir = root / dir_name
    work_dir.mkdir(parents=True, exist_ok=True)

    command = [
        yt_dlp,
        "--no-playlist",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        lang,
        "--sub-format",
        subtitle_format,
        "--convert-subs",
        "vtt",
        "--write-info-json",
        "--paths",
        str(work_dir),
        "--output",
        "%(title).180B [%(id)s].%(ext)s",
    ]
    command.extend(["--js-runtimes", yt_dlp_js_runtimes])
    if no_video:
        command.append("--skip-download")

    command.append(url)
    run_subprocess(command, cwd=work_dir)

    subtitle_files, video_files, info_files = scan_work_dir(work_dir)
    selected_subtitle = choose_subtitle(subtitle_files, lang)
    title = choose_download_title(info_files, video_files, selected_subtitle)
    work_dir = finalize_download_dir(
        current_dir=work_dir,
        root=root,
        title=title,
        timestamp=timestamp,
        job_name=job_name,
    )
    subtitle_files, video_files, info_files = scan_work_dir(work_dir)
    selected_subtitle = choose_subtitle(subtitle_files, lang)

    manifest = {
        "url": url,
        "lang": lang,
        "work_dir": str(work_dir),
        "video_files": [str(path) for path in video_files],
        "subtitle_files": [str(path) for path in subtitle_files],
        "selected_subtitle": str(selected_subtitle) if selected_subtitle else None,
        "info_files": [str(path) for path in info_files],
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    (work_dir / "download-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return DownloadResult(
        work_dir=work_dir,
        video_files=video_files,
        subtitle_files=subtitle_files,
        selected_subtitle=selected_subtitle,
        info_files=info_files,
    )


def scan_work_dir(work_dir: Path) -> tuple[list[Path], list[Path], list[Path]]:
    """Return (subtitle_files, video_files, info_files) found under ``work_dir``."""
    files = [path for path in work_dir.rglob("*") if path.is_file()]
    subtitle_files = sorted(p for p in files if p.suffix.lower() in SUBTITLE_EXTENSIONS)
    video_files = sorted(p for p in files if p.suffix.lower() in VIDEO_EXTENSIONS)
    info_files = sorted(p for p in files if p.name.endswith(".info.json"))
    return subtitle_files, video_files, info_files


def choose_subtitle(files: list[Path], lang_expression: str) -> Path | None:
    if not files:
        return None

    tokens = subtitle_lang_tokens(lang_expression)

    def score(path: Path) -> tuple[int, int, str]:
        name = path.name.lower()
        score_value = SUBTITLE_EXTENSION_SCORES.get(path.suffix.lower(), 10)

        if any(token in name for token in tokens):
            score_value += 30
        if "auto" in name or "asr" in name:
            score_value -= 5
        if "orig" in name:
            score_value -= 3

        return (score_value, -len(name), name)

    return max(files, key=score)


def subtitle_lang_tokens(lang_expression: str) -> list[str]:
    return [
        token
        for raw_token in lang_expression.split(",")
        if (token := raw_token.strip().lower().replace("*", ""))
    ]


def choose_download_title(
    info_files: list[Path], video_files: list[Path], selected_subtitle: Path | None
) -> str:
    for info_path in info_files:
        try:
            data = json.loads(info_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        title = data.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()

    if video_files:
        return strip_download_stem(video_files[0].stem)
    if selected_subtitle is not None:
        return strip_download_stem(selected_subtitle.stem)
    return "download"


def strip_download_stem(stem: str) -> str:
    stripped = re.sub(r"\.[A-Za-z0-9_-]+(?:\.ruby(?:\.corrected)?)?$", "", stem)
    stripped = re.sub(r"\s+\[[^\]]+\]$", "", stripped)
    return stripped.strip() or stem


def finalize_download_dir(
    *, current_dir: Path, root: Path, title: str, timestamp: str, job_name: str
) -> Path:
    target_dir = unique_dir_path(
        root
        / build_output_dir_name(title=title, timestamp=timestamp, job_name=job_name)
    )
    if target_dir == current_dir:
        return current_dir
    current_dir.rename(target_dir)
    return target_dir


def build_output_dir_name(*, title: str, timestamp: str, job_name: str) -> str:
    safe_title = sanitize_dir_name(title) or "download"
    safe_job = sanitize_dir_name(job_name)
    if safe_job:
        return f"{safe_title} {timestamp} - {safe_job}"
    return f"{safe_title} {timestamp}"


def sanitize_dir_name(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r'[<>:"/\\|?*]+', " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.rstrip(". ")
    return cleaned[:96]


def unique_dir_path(path: Path) -> Path:
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.name} ({index})")
        if not candidate.exists():
            return candidate
        index += 1
