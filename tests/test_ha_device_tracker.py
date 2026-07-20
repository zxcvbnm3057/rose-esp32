"""Regression tests for Home Assistant BLE tracker lifecycle callbacks."""
import asyncio
import importlib.util
import sys
import types
from pathlib import Path


class FakeEntity:
    def __init__(self, coordinator=None) -> None:
        self.coordinator = coordinator
        self._on_remove = []
        self.entity_id = "device_tracker.phone"
        self.hass = types.SimpleNamespace(
            bus=types.SimpleNamespace(async_listen=lambda event, callback: lambda: None),
            async_create_task=lambda coroutine: asyncio.run(coroutine),
        )

    async def async_added_to_hass(self) -> None:
        return None

    def async_on_remove(self, callback) -> None:
        self._on_remove.append(callback)


class FakeCoordinatorEntity(FakeEntity):
    pass


class FakeScannerEntity:
    pass


def load_device_tracker_module(monkeypatch):
    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    device_tracker = types.ModuleType("homeassistant.components.device_tracker")
    helpers = types.ModuleType("homeassistant.helpers")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")
    device_tracker.ScannerEntity = FakeScannerEntity
    device_tracker.SourceType = types.SimpleNamespace(BLUETOOTH_LE="bluetooth_le")
    update_coordinator.CoordinatorEntity = FakeCoordinatorEntity
    entity_registry.EVENT_ENTITY_REGISTRY_UPDATED = "entity_registry_updated"

    rose_package = types.ModuleType("custom_components.rose")
    rose_package.__path__ = []
    const = types.ModuleType("custom_components.rose.const")
    const.DOMAIN = "rose"
    const.CONF_BLE_DEVICES = "ble_devices"
    const.SUBENTRY_TYPE_BLE = "ble"

    modules = {
        "homeassistant": homeassistant,
        "homeassistant.components": components,
        "homeassistant.components.device_tracker": device_tracker,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.entity_registry": entity_registry,
        "homeassistant.helpers.update_coordinator": update_coordinator,
        "custom_components.rose": rose_package,
        "custom_components.rose.const": const,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    module_path = Path(__file__).parents[1] / "custom_components" / "rose" / "device_tracker.py"
    spec = importlib.util.spec_from_file_location("custom_components.rose.device_tracker", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tracker_preserves_entity_remove_callbacks(monkeypatch):
    module = load_device_tracker_module(monkeypatch)
    removed_macs = []
    tracker = module.RoseBleTracker(
        types.SimpleNamespace(data={"connected": True, "ble": {}}),
        "aa:bb:cc:dd:ee:ff",
        lambda mac: remove_mac(removed_macs, mac),
    )

    asyncio.run(tracker.async_added_to_hass())

    assert isinstance(tracker._on_remove, list)
    assert len(tracker._on_remove) == 1
    tracker._entity_registry_updated(
        types.SimpleNamespace(
            data={"action": "remove", "entity_id": "device_tracker.phone"}
        )
    )
    assert removed_macs == ["aa:bb:cc:dd:ee:ff"]


def test_setup_creates_only_manually_selected_trackers(monkeypatch):
    module = load_device_tracker_module(monkeypatch)
    coordinator = types.SimpleNamespace(
        data={
            "connected": True,
            "ble": {
                "aa:bb:cc:dd:ee:ff": {"name": "Selected"},
                "11:22:33:44:55:66": {"name": "Discovered only"},
            },
        }
    )
    entry = types.SimpleNamespace(
        entry_id="entry",
        subentries={
            "ble-sync": types.SimpleNamespace(
                subentry_type="ble",
                data={"ble_devices": ["aa:bb:cc:dd:ee:ff"]},
            )
        },
    )
    hass = types.SimpleNamespace(
        data={"rose": {"entry": {"coordinator": coordinator}}},
        config_entries=types.SimpleNamespace(async_update_subentry=lambda *args, **kwargs: None),
    )
    added_entities = []
    added_subentry_ids = []

    def add_entities(entities, config_subentry_id=None):
        added_entities.extend(entities)
        added_subentry_ids.append(config_subentry_id)

    asyncio.run(
        module.async_setup_entry(
            hass,
            entry,
            add_entities,
        )
    )

    assert [entity._mac for entity in added_entities] == ["aa:bb:cc:dd:ee:ff"]
    assert added_subentry_ids == ["ble-sync"]


async def remove_mac(removed_macs, mac):
    removed_macs.append(mac)