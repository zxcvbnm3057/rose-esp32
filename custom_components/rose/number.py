"""TCL air-conditioner timer controls for Rose."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode

from .const import CONF_CLIMATES, DOMAIN, configured_devices

CLIMATE_CAPABILITIES = {"tcl": {"timer"}}


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        RoseClimateTimer(runtime, key, config)
        for key, config in configured_devices(entry, CONF_CLIMATES).items()
    )


class RoseClimateTimer(NumberEntity):
    _attr_has_entity_name = True
    _attr_assumed_state = True
    _attr_translation_key = "off_timer"
    _attr_native_min_value = 0
    _attr_native_max_value = 1440
    _attr_native_step = 10
    _attr_native_unit_of_measurement = "min"
    _attr_mode = NumberMode.BOX

    def __init__(self, runtime: dict, key: str, config: dict) -> None:
        self._runtime = runtime
        self._key = key
        self._attr_unique_id = f"rose_climate_{key}_timer"
        self._device_name = config.get("name", key.replace("_", " ").title())
        protocol = config.get("protocol", "tcl")
        self._supported = "timer" in CLIMATE_CAPABILITIES.get(protocol, set())

    @property
    def _climate(self):
        return self._runtime.get("climate_entities", {}).get(self._key)

    @property
    def native_value(self):
        climate = self._climate
        return climate.extra_state_attributes.get("timer_minutes", 0) if climate else 0

    @property
    def available(self):
        return self._supported and self._climate is not None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"climate_{self._key}")},
            "name": self._device_name,
            "manufacturer": "Rose",
            "model": "TCL infrared climate controller",
            "via_device": (DOMAIN, "platform"),
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._climate is not None:
            self.async_on_remove(self._climate.add_control_listener(self.async_write_ha_state))

    async def async_set_native_value(self, value: float) -> None:
        if not self._supported:
            return
        await self._climate.async_send_extended(timer_minutes=int(value))
        self.async_write_ha_state()