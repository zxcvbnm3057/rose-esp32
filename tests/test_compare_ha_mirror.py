import json
from pathlib import Path

from tests.compare_ha_mirror import compare_directories


def test_json_formatting_differences_are_ignored(tmp_path: Path) -> None:
    source = tmp_path / "source"
    mirror = tmp_path / "mirror"
    source.mkdir()
    mirror.mkdir()
    data = {"name": "Rose", "value": 1}
    (source / "data.json").write_text(json.dumps(data), encoding="utf-8")
    (mirror / "data.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    assert compare_directories(source, mirror) == []


def test_json_value_differences_are_reported(tmp_path: Path) -> None:
    source = tmp_path / "source"
    mirror = tmp_path / "mirror"
    source.mkdir()
    mirror.mkdir()
    (source / "data.json").write_text('{"value": 1}', encoding="utf-8")
    (mirror / "data.json").write_text('{"value": 2}', encoding="utf-8")

    assert compare_directories(source, mirror) == ["JSON content differs: data.json"]


def test_non_json_differences_are_reported(tmp_path: Path) -> None:
    source = tmp_path / "source"
    mirror = tmp_path / "mirror"
    source.mkdir()
    mirror.mkdir()
    (source / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (mirror / "module.py").write_text("VALUE = 2\n", encoding="utf-8")

    assert compare_directories(source, mirror) == ["File content differs: module.py"]


def test_missing_files_are_reported(tmp_path: Path) -> None:
    source = tmp_path / "source"
    mirror = tmp_path / "mirror"
    source.mkdir()
    mirror.mkdir()
    (source / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

    assert compare_directories(source, mirror) == ["Missing from mirror: module.py"]