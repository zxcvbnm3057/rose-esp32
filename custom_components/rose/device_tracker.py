"""BLE presence trackers for known Rose devices."""
from __future__ import annotations

from homeassistant.components.device_tracker import ScannerEntity, SourceType
from homeassistant.helpers.entity_registry import EVENT_ENTITY_REGISTRY_UPDATED
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_BLE_DEVICES, DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime["coordinator"]
    selected_macs = entry.options.get(CONF_BLE_DEVICES, [])

    async def remove_selected_mac(mac: str) -> None:
        current = entry.options.get(CONF_BLE_DEVICES, [])
        if mac not in current:
            return
        hass.config_entries.async_update_entry(
            entry,
            options={
                **entry.options,
                CONF_BLE_DEVICES: [selected for selected in current if selected != mac],
            },
        )

    async_add_entities(
        [RoseBleTracker(coordinator, mac, remove_selected_mac) for mac in selected_macs]
    )


class RoseBleTracker(CoordinatorEntity, ScannerEntity):
    _attr_has_entity_name = True
    _attr_source_type = SourceType.BLUETOOTH_LE

    def __init__(self, coordinator, mac: str, remove_selected_mac) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._remove_selected_mac = remove_selected_mac
        self._attr_unique_id = f"rose_ble_{self._mac.replace(':', '')}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_ENTITY_REGISTRY_UPDATED, self._entity_registry_updated)
        )

    def _entity_registry_updated(self, event) -> None:
        if event.data.get("action") != "remove" or event.data.get("entity_id") != self.entity_id:
            return
        self.hass.async_create_task(self._remove_selected_mac(self._mac))

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