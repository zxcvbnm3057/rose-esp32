"""Rose connectivity sensors."""
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_BLE_DEVICES, DOMAIN, SUBENTRY_TYPE_BLE


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([RoseConnectionSensor(coordinator)])
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_BLE:
            continue
        async_add_entities(
            [
                RoseBleOnlineSensor(coordinator, mac)
                for mac in subentry.data.get(CONF_BLE_DEVICES, [])
            ],
            config_subentry_id=subentry_id,
        )


class RoseConnectionSensor(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "ESP32 connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_unique_id = "rose_platform_connection"

    @property
    def is_on(self):
        return bool(self.coordinator.data and self.coordinator.data.get("connected"))

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, "platform")}, "name": "Rose Platform", "manufacturer": "Rose"}


class RoseBleOnlineSensor(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, mac: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = f"rose_ble_{mac.replace(':', '')}_online"

    @property
    def is_on(self):
        state = (self.coordinator.data or {}).get("ble", {}).get(self._mac, {})
        return bool(state.get("home"))

    @property
    def available(self):
        return super().available and bool((self.coordinator.data or {}).get("connected"))

    @property
    def device_info(self):
        state = (self.coordinator.data or {}).get("ble", {}).get(self._mac, {})
        return {
            "identifiers": {(DOMAIN, f"ble_{self._mac}")},
            "connections": {("bluetooth", self._mac)},
            "name": state.get("name", self._mac),
            "manufacturer": "Rose",
            "model": "BLE presence device",
            "via_device": (DOMAIN, "platform"),
        }
