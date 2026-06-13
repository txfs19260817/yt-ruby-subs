from pathlib import Path

from yt_ruby_subs.clean import clean_project


def test_clean_project_removes_logs_cache_and_coverage(tmp_path: Path) -> None:
    for directory in ("logs", "run-logs", "__pycache__", ".pytest_cache", ".ruff_cache"):
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
