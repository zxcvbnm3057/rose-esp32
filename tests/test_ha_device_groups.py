"""Regression tests for Rose config subentry device grouping."""
import importlib.util
from pathlib import Path
import sys
import types


def load_device_groups(monkeypatch):
    rose_package = types.ModuleType("custom_components.rose")
    rose_package.__path__ = []
    const = types.ModuleType("custom_components.rose.const")
    const.CONF_BLE_DEVICES = "ble_devices"
    const.CONF_KEY = "key"
    const.DOMAIN = "rose"
    const.SUBENTRY_TYPE_BLE = "ble"
    const.SUBENTRY_TYPE_CLIMATE = "climate"
    const.SUBENTRY_TYPE_LIGHT = "light"
    const.climate_protocol_name = lambda config: config.get("protocol", "tcl")
    monkeypatch.setitem(sys.modules, "custom_components.rose", rose_package)
    monkeypatch.setitem(sys.modules, "custom_components.rose.const", const)

    module_path = Path(__file__).parents[1] / "custom_components" / "rose" / "device_groups.py"
    spec = importlib.util.spec_from_file_location("custom_components.rose.device_groups", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_subentries_create_distinct_device_groups(monkeypatch):
    module = load_device_groups(monkeypatch)
    entry = types.SimpleNamespace(
        subentries={
            "climate-sub": types.SimpleNamespace(
                subentry_type="climate",
                data={"key": "living_room", "name": "Living room AC", "protocol": "tcl"},
            ),
            "light-sub": types.SimpleNamespace(
                subentry_type="light",
                data={"key": "desk", "name": "Desk light"},
            ),
            "ble-sub": types.SimpleNamespace(
                subentry_type="ble",
                data={"ble_devices": ["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"]},
            ),
        }
    )

    specs = module.device_group_specs(
        entry,
        {"aa:bb:cc:dd:ee:ff": {"name": "Phone"}},
    )

    assert [(spec["subentry_id"], spec["identifier"]) for spec in specs] == [
        ("climate-sub", ("rose", "climate_living_room")),
        ("light-sub", ("rose", "light_desk")),
        ("ble-sub", ("rose", "ble_aa:bb:cc:dd:ee:ff")),
        ("ble-sub", ("rose", "ble_11:22:33:44:55:66")),
    ]
    assert all(spec["identifier"] != ("rose", "platform") for spec in specs)
    assert specs[2]["connection"] == ("bluetooth", "aa:bb:cc:dd:ee:ff")
    assert specs[2]["name"] == "Phone"