"""Rose platform connectivity sensor."""
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([RoseConnectionSensor(hass.data[DOMAIN][entry.entry_id]["coordinator"])])


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
