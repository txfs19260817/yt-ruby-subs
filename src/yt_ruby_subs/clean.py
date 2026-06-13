import argparse
import shutil
from collections.abc import Iterable
from pathlib import Path

CLEAN_NAMES = {"logs", "run-logs", "__pycache__", ".coverage"}
SKIP_DIRS = {".git", ".venv", "venv", ".tox", ".nox", "node_modules"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove local logs, cache directories, and coverage files.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Project root to clean. Defaults to the current directory.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print targets without deleting them.")
    args = parser.parse_args()

    removed = clean_project(args.root, dry_run=args.dry_run)
    action = "would remove" if args.dry_run else "removed"
    for path in removed:
        print(f"{action}: {path}")
    if not removed:
        print("nothing to clean")
    return 0


def clean_project(root: Path, *, dry_run: bool = False) -> list[Path]:
    root = root.resolve()
    targets = dedupe_nested_targets(find_clean_targets(root))
    for target in targets:
        if dry_run:
            continue
        remove_path(target)
    return targets


def find_clean_targets(root: Path) -> list[Path]:
    targets: list[Path] = []
    for path in root.rglob("*"):
        if should_skip(path, root):
            continue
        if is_clean_target(path):
            targets.append(path)
    return targets


def should_skip(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    return any(part in SKIP_DIRS for part in relative.parts)


def is_clean_target(path: Path) -> bool:
    return path.name in CLEAN_NAMES or path.name.endswith("cache")


def dedupe_nested_targets(paths: Iterable[Path]) -> list[Path]:
    selected: list[Path] = []
    for path in sorted(paths, key=lambda item: len(item.parts)):
        if any(parent in selected for parent in path.parents):
            continue
        selected.append(path)
    return selected


def remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
        return
    path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
