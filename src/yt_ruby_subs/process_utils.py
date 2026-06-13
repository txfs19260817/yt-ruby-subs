import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .errors import CliError


def run_subprocess(
    command: list[str],
    *,
    cwd: Path,
    stdin: str | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    print("+", format_command(command))
    completed = subprocess.run(
        command,
        cwd=cwd,
        input=stdin,
        text=True,
        encoding="utf-8",
        capture_output=capture_output,
        check=False,
        env=os.environ.copy(),
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() if completed.stderr else ""
        stdout = completed.stdout.strip() if completed.stdout else ""
        detail = stderr or stdout or f"exit code {completed.returncode}"
        raise CliError(detail)
    return completed


def resolve_command(raw: str, *, windows_preferred: tuple[str, ...]) -> str:
    candidates = list(windows_preferred) if os.name == "nt" else [raw]
    if raw not in candidates:
        candidates.append(raw)

    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    raise CliError(f"command not found: {raw}")


def parse_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CliError(f"failed to parse JSON from {path}: {exc}") from exc


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def format_command(command: list[str]) -> str:
    return subprocess.list2cmdline(command)
