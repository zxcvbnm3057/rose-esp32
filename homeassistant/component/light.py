"""UART-backed Rose light entities."""
from __future__ import annotations

from homeassistant.components.light import LightEntity
from homeassistant.const import STATE_ON
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_LIGHTS, DOMAIN, configured_devices


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        RoseUartLight(runtime["client"], key, config)
        for key, config in configured_devices(entry, CONF_LIGHTS).items()
    )


class RoseUartLight(LightEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_assumed_state = True

    def __init__(self, client, key: str, config: dict) -> None:
        self._client = client
        self._key = key
        self._config = config
        self._attr_name = config.get("name", key.replace("_", " ").title())
        self._attr_unique_id = f"rose_light_{key}"
        self._attr_is_on = False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"light_{self._key}")},
            "name": self._attr_name,
            "manufacturer": "Rose",
            "model": "UART light controller",
            "via_device": (DOMAIN, "platform"),
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == STATE_ON

    async def async_turn_on(self, **kwargs):
        await self._client.uart_send(int(self._config.get("uart_id", 1)), self._config["on"])
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        await self._client.uart_send(int(self._config.get("uart_id", 1)), self._config["off"])
        self._attr_is_on = False
        self.async_write_ha_state()
