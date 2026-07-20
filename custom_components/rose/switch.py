"""Extended TCL air-conditioner switches for Rose."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity

from .const import (
    DOMAIN,
    SUBENTRY_TYPE_CLIMATE,
    configured_subentries,
)

CLIMATE_CAPABILITIES = {
    "tcl": {"econo", "health", "turbo", "light", "aux_heat"},
}

SWITCHES = {
    "econo": "econo",
    "health": "health",
    "turbo": "turbo",
    "light": "light",
    "aux_heat": "aux_heat",
    "sleep": "sleep",
}


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    for subentry_id, key, config in configured_subentries(entry, SUBENTRY_TYPE_CLIMATE):
        async_add_entities(
            [
                RoseClimateSwitch(runtime, key, config, option, name)
                for option, name in SWITCHES.items()
            ],
            config_subentry_id=subentry_id,
        )


class RoseClimateSwitch(SwitchEntity):
    _attr_has_entity_name = True
    _attr_assumed_state = True

    def __init__(self, runtime: dict, key: str, config: dict, option: str, translation_key: str) -> None:
        self._runtime = runtime
        self._key = key
        self._option = option
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"rose_climate_{key}_{option}"
        protocol = config.get("protocol", "tcl")
        self._supported = option in CLIMATE_CAPABILITIES.get(protocol, set())

    @property
    def _climate(self):
        return self._runtime.get("climate_entities", {}).get(self._key)

    @property
    def is_on(self):
        climate = self._climate
        return bool(climate and climate.extra_state_attributes.get(self._option))

    @property
    def available(self):
        return self._supported and self._climate is not None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, "platform")},
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._climate is not None:
            self.async_on_remove(self._climate.add_control_listener(self.async_write_ha_state))

    async def _set(self, enabled: bool) -> None:
        if not self._supported:
            return
        await self._climate.async_send_extended(**{self._option: enabled})
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        await self._set(True)

    async def async_turn_off(self, **kwargs):
        await self._set(False)