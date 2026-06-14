import sys
from pathlib import Path

import pytest

from yt_ruby_subs import clean
from yt_ruby_subs.clean import clean_project


def test_clean_project_removes_logs_cache_and_coverage(tmp_path: Path) -> None:
    for directory in (
        "logs",
        "run-logs",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
    ):
        path = tmp_path / directory
        path.mkdir()
        (path / "file.txt").write_text("data", encoding="utf-8")
    coverage = tmp_path / ".coverage"
    coverage.write_text("coverage", encoding="utf-8")
    keep = tmp_path / "keep.txt"
    keep.write_text("keep", encoding="utf-8")

    removed = clean_project(tmp_path)

    assert {path.name for path in removed} == {
        "logs",
        "run-logs",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".coverage",
    }
    assert not coverage.exists()
    assert not (tmp_path / "logs").exists()
    assert not (tmp_path / "__pycache__").exists()
    assert keep.exists()


def test_clean_project_skips_virtualenv_and_git_dirs(tmp_path: Path) -> None:
    for directory in (".venv", ".git"):
        cache = tmp_path / directory / "__pycache__"
        cache.mkdir(parents=True)
        (cache / "file.txt").write_text("data", encoding="utf-8")

    removed = clean_project(tmp_path)

    assert removed == []
    assert (tmp_path / ".venv" / "__pycache__").exists()
    assert (tmp_path / ".git" / "__pycache__").exists()


def test_clean_project_dry_run_preserves_targets(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()

    removed = clean_project(tmp_path, dry_run=True)

    assert removed == [logs]
    assert logs.exists()


def test_dedupe_nested_targets_skips_children(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    nested_cache = logs / ".pytest_cache"
    nested_cache.mkdir(parents=True)

    assert clean.dedupe_nested_targets([nested_cache, logs]) == [logs]


def test_should_skip_paths_outside_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside"

    assert clean.should_skip(outside, tmp_path) is True


def test_main_prints_dry_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(
        sys,
        "argv",
        ["yt-ruby-subs-clean", "--root", str(tmp_path), "--dry-run"],
    )

    assert clean.main() == 0

    assert f"would remove: {logs.resolve()}" in capsys.readouterr().out
    assert logs.exists()


def test_main_prints_nothing_to_clean(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["yt-ruby-subs-clean", "--root", str(tmp_path)])

    assert clean.main() == 0

    assert "nothing to clean" in capsys.readouterr().out
