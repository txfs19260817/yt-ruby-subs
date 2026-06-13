import subprocess
from pathlib import Path
from typing import Any

import pytest

from yt_ruby_subs import process_utils
from yt_ruby_subs.errors import CliError


def test_run_subprocess_returns_completed_process(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(process_utils.subprocess, "run", fake_run)

    completed = process_utils.run_subprocess(
        ["tool", "arg"],
        cwd=tmp_path,
        stdin="input text",
        capture_output=True,
    )

    assert completed.stdout == "ok"
    assert calls[0]["command"] == ["tool", "arg"]
    assert calls[0]["cwd"] == tmp_path
    assert calls[0]["input"] == "input text"
    assert calls[0]["capture_output"] is True
    assert calls[0]["check"] is False


def test_run_subprocess_raises_cli_error_with_process_detail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 2, stdout="stdout detail", stderr="stderr detail")

    monkeypatch.setattr(process_utils.subprocess, "run", fake_run)

    with pytest.raises(CliError, match="stderr detail"):
        process_utils.run_subprocess(["tool"], cwd=tmp_path)


def test_resolve_command_prefers_windows_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    monkeypatch.setattr(process_utils.os, "name", "nt")

    def fake_which(candidate: str) -> str | None:
        seen.append(candidate)
        if candidate == "tool.exe":
            return "C:/bin/tool.exe"
        return None

    monkeypatch.setattr(process_utils.shutil, "which", fake_which)

    assert process_utils.resolve_command("tool", windows_preferred=("tool.exe", "tool.cmd")) == "C:/bin/tool.exe"
    assert seen == ["tool.exe"]


def test_resolve_command_raises_when_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(process_utils.os, "name", "posix")
    monkeypatch.setattr(process_utils.shutil, "which", lambda candidate: None)

    with pytest.raises(CliError, match="command not found: missing-tool"):
        process_utils.resolve_command("missing-tool", windows_preferred=("missing-tool.exe",))


def test_parse_json_file_reports_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{bad", encoding="utf-8")

    with pytest.raises(CliError, match="failed to parse JSON"):
        process_utils.parse_json_file(path)


def test_normalize_newlines_and_format_command() -> None:
    assert process_utils.normalize_newlines("a\r\nb\rc") == "a\nb\nc"
    assert "hello world" in process_utils.format_command(["tool", "hello world"])
