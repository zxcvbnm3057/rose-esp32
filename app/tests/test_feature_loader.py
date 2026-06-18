"""Feature loader tests."""
from __future__ import annotations

import sys
from pathlib import Path
import shutil

from app.src.feature_loader import discover_features


def test_discover_features_supports_file_and_package_modules() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    package_dir = repo_root / "app" / "src" / "features" / "loader_test_pkg"
    package_dir.mkdir(exist_ok=True)
    init_file = package_dir / "__init__.py"
    init_file.write_text(
        "from app.src.models import FeatureSpec\n"
        "async def handle(context):\n"
        "    return None\n"
        "FEATURE = FeatureSpec(name='loader_test_pkg', handler=handle)\n",
        encoding="utf-8",
    )
    try:
        names = {feature.name for feature in discover_features()}
        assert "ac_ir_control" in names
        assert "light_switch" in names
        assert "loader_test_pkg" in names
    finally:
        if package_dir.exists():
            shutil.rmtree(package_dir, ignore_errors=True)
        sys.modules.pop("app.src.features.loader_test_pkg", None)
