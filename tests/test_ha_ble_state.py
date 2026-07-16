"""Regression tests for Home Assistant BLE object synchronization."""
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "rose" / "ble_state.py"
spec = importlib.util.spec_from_file_location("rose_ble_state", MODULE_PATH)
assert spec and spec.loader
rose_ble_state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rose_ble_state)

merge_ble_devices = rose_ble_state.merge_ble_devices


def test_in_range_snapshot_creates_object_without_status_gate():
    result = merge_ble_devices(
        {},
        {},
        [{"mac": "AA-BB-CC-DD-EE-FF", "rssi": -45}],
    )

    assert result == {
        "aa:bb:cc:dd:ee:ff": {
            "home": True,
            "rssi": -45,
            "name": "aa:bb:cc:dd:ee:ff",
        }
    }


def test_named_device_creates_offline_object_without_snapshot():
    result = merge_ble_devices(
        {},
        {"AA:BB:CC:DD:EE:FF": "Phone"},
        [],
    )

    assert result == {
        "aa:bb:cc:dd:ee:ff": {
            "home": False,
            "rssi": None,
            "name": "Phone",
        }
    }