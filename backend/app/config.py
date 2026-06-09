"""Application configuration — loads hardware_config.json."""
import json
import os
from pathlib import Path
from functools import lru_cache
from typing import Any

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "hardware_config.json"


@lru_cache()
def load_hardware_config() -> dict[str, Any]:
    """Load and return the hardware configuration JSON."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"hardware_config.json not found at {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_capabilities() -> dict[str, Any]:
    return load_hardware_config().get("capabilities", {})


def get_pins() -> list[dict[str, Any]]:
    return load_hardware_config().get("pins", [])


def get_feature_groups() -> list[dict[str, Any]]:
    return load_hardware_config().get("feature_groups", [])


def get_chip_name() -> str:
    return load_hardware_config().get("chip", {}).get("name", "Unknown")
