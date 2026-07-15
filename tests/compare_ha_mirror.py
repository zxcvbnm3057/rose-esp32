"""Compare the Home Assistant source and HACS mirror directories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def collect_files(root: Path) -> dict[Path, Path]:
    return {
        path.relative_to(root): path
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def compare_directories(source: Path, mirror: Path) -> list[str]:
    source_files = collect_files(source)
    mirror_files = collect_files(mirror)
    errors: list[str] = []

    for relative_path in sorted(source_files.keys() - mirror_files.keys()):
        errors.append(f"Missing from mirror: {relative_path}")
    for relative_path in sorted(mirror_files.keys() - source_files.keys()):
        errors.append(f"Only in mirror: {relative_path}")

    for relative_path in sorted(source_files.keys() & mirror_files.keys()):
        source_path = source_files[relative_path]
        mirror_path = mirror_files[relative_path]
        if relative_path.suffix == ".json":
            try:
                source_content = json.loads(source_path.read_text(encoding="utf-8"))
                mirror_content = json.loads(mirror_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                errors.append(f"Invalid JSON in {relative_path}: {error}")
                continue
            if source_content != mirror_content:
                errors.append(f"JSON content differs: {relative_path}")
        elif source_path.read_bytes() != mirror_path.read_bytes():
            errors.append(f"File content differs: {relative_path}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("mirror", type=Path)
    arguments = parser.parse_args()

    errors = compare_directories(arguments.source, arguments.mirror)
    if errors:
        print("\n".join(errors))
        return 1
    print("Home Assistant source and HACS mirror match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())