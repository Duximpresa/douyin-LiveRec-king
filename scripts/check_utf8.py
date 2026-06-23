"""Validate repository text files as UTF-8 or UTF-8-SIG."""

from __future__ import annotations

import sys
from pathlib import Path


EXTENSIONS = {".py", ".md", ".ini", ".bat"}
IGNORED_PARTS = {
    ".git",
    ".venv",
    ".build-venv",
    "build",
    "dist",
    "release",
    "__pycache__",
}


def candidates(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            continue
        if any(part in IGNORED_PARTS for part in path.parts):
            continue
        yield path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    failures: list[str] = []
    checked = 0
    for path in candidates(root):
        checked += 1
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            failures.append(f"{path.relative_to(root)}: {exc}")
            continue
        if "\ufffd" in text:
            failures.append(f"{path.relative_to(root)}: contains U+FFFD")
    if failures:
        print("UTF-8 validation failed:")
        print("\n".join(failures))
        return 1
    print(f"UTF-8 validation passed: {checked} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
