"""BLE presence trackers for known Rose devices."""
from __future__ import annotations

from homeassistant.components.device_tracker import ScannerEntity, SourceType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime["coordinator"]
    added_macs: set[str] = set()

    def add_tracker(mac: str) -> None:
        if mac in added_macs:
            return
        added_macs.add(mac)
        async_add_entities([RoseBleTracker(coordinator, mac, added_macs.discard)])

    for mac in (coordinator.data or {}).get("ble", {}):
        add_tracker(mac)
    entry.async_on_unload(coordinator.async_add_ble_discovered_callback(add_tracker))

    def discover_from_snapshot() -> None:
        for mac in (coordinator.data or {}).get("ble", {}):
            add_tracker(mac)

    entry.async_on_unload(coordinator.async_add_listener(discover_from_snapshot))


class RoseBleTracker(CoordinatorEntity, ScannerEntity):
    _attr_has_entity_name = True
    _attr_source_type = SourceType.BLUETOOTH_LE

    def __init__(self, coordinator, mac: str, on_remove) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._on_remove = on_remove
        self._attr_unique_id = f"rose_ble_{self._mac.replace(':', '')}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(lambda: self._on_remove(self._mac))

    @property
    def name(self):
        return (self.coordinator.data or {}).get("ble", {}).get(self._mac, {}).get("name", self._mac)

    @property
    def is_connected(self):
        state = (self.coordinator.data or {}).get("ble", {}).get(self._mac, {})
        return bool(state.get("home"))

    @property
    def extra_state_attributes(self):
        state = (self.coordinator.data or {}).get("ble", {}).get(self._mac, {})
        return {"mac": self._mac, "rssi": state.get("rssi")}

    @property
    def available(self):
        return super().available and bool((self.coordinator.data or {}).get("connected"))

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"ble_{self._mac}")},
            "connections": {("bluetooth", self._mac)},
            "name": self.name,
            "via_device": (DOMAIN, "platform"),
        }