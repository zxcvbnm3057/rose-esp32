"""Regression tests for Home Assistant BLE online sensors."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import types


class FakeCoordinatorEntity:
    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator

    @property
    def available(self):
        return True


class FakeBinarySensorEntity:
    pass


def load_binary_sensor_module(monkeypatch):
    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    binary_sensor = types.ModuleType("homeassistant.components.binary_sensor")
    helpers = types.ModuleType("homeassistant.helpers")
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")
    binary_sensor.BinarySensorDeviceClass = types.SimpleNamespace(CONNECTIVITY="connectivity")
    binary_sensor.BinarySensorEntity = FakeBinarySensorEntity
    update_coordinator.CoordinatorEntity = FakeCoordinatorEntity

    rose_package = types.ModuleType("custom_components.rose")
    rose_package.__path__ = []
    const = types.ModuleType("custom_components.rose.const")
    const.CONF_BLE_DEVICES = "ble_devices"
    const.DOMAIN = "rose"
    const.SUBENTRY_TYPE_BLE = "ble"

    modules = {
        "homeassistant": homeassistant,
        "homeassistant.components": components,
        "homeassistant.components.binary_sensor": binary_sensor,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.update_coordinator": update_coordinator,
        "custom_components.rose": rose_package,
        "custom_components.rose.const": const,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    module_path = Path(__file__).parents[1] / "custom_components" / "rose" / "binary_sensor.py"
    spec = importlib.util.spec_from_file_location("custom_components.rose.binary_sensor", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ble_online_sensor_reflects_presence_and_device(monkeypatch):
    module = load_binary_sensor_module(monkeypatch)
    coordinator = types.SimpleNamespace(
        data={
            "connected": True,
            "ble": {
                "aa:bb:cc:dd:ee:ff": {
                    "home": True,
                    "name": "Phone",
                }
            },
        }
    )

    sensor = module.RoseBleOnlineSensor(coordinator, "aa:bb:cc:dd:ee:ff")

    assert sensor.is_on is True
    assert sensor.available is True
    assert sensor._attr_unique_id == "rose_ble_aabbccddeeff_online"
    assert sensor.device_info["identifiers"] == {("rose", "ble_aa:bb:cc:dd:ee:ff")}
    assert sensor.device_info["name"] == "Phone"

    coordinator.data["ble"]["aa:bb:cc:dd:ee:ff"]["home"] = False
    assert sensor.is_on is False

    coordinator.data["connected"] = False
    assert sensor.available is False


def test_setup_creates_sensors_only_for_selected_ble_devices(monkeypatch):
    module = load_binary_sensor_module(monkeypatch)
    coordinator = types.SimpleNamespace(data={"connected": True, "ble": {}})
    entry = types.SimpleNamespace(
        entry_id="entry",
        subentries={
            "ble-sync": types.SimpleNamespace(
                subentry_type="ble",
                data={"ble_devices": ["aa:bb:cc:dd:ee:ff"]},
            ),
            "light": types.SimpleNamespace(subentry_type="light", data={}),
        },
    )
    hass = types.SimpleNamespace(data={"rose": {"entry": {"coordinator": coordinator}}})
    additions = []

    def add_entities(entities, config_subentry_id=None):
        additions.append((list(entities), config_subentry_id))

    asyncio.run(module.async_setup_entry(hass, entry, add_entities))

    assert len(additions) == 2
    assert isinstance(additions[0][0][0], module.RoseConnectionSensor)
    assert additions[0][1] is None
    assert [entity._mac for entity in additions[1][0]] == ["aa:bb:cc:dd:ee:ff"]
    assert additions[1][1] == "ble-sync"