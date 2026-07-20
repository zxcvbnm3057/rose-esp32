"""TCL infrared climate entities for Rose."""
from __future__ import annotations

import math
from collections.abc import Callable

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import ClimateEntityFeature, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DOMAIN,
    SUBENTRY_TYPE_CLIMATE,
    configured_subentries,
)
from .protocols.tcl import TclFanMode, TclHvacMode, TclPowerState, TclState, encode_tcl_ir_signal

HVAC_TO_TCL = {
    HVACMode.AUTO: TclHvacMode.AUTO,
    HVACMode.COOL: TclHvacMode.COOL,
    HVACMode.HEAT: TclHvacMode.HEAT,
    HVACMode.DRY: TclHvacMode.DRY,
    HVACMode.FAN_ONLY: TclHvacMode.FAN_ONLY,
}


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    entities = {}
    for subentry_id, key, config in configured_subentries(entry, SUBENTRY_TYPE_CLIMATE):
        if config.get("protocol", "tcl") != "tcl":
            continue
        entity = RoseTclClimate(runtime["client"], key, config)
        entities[key] = entity
        async_add_entities([entity], config_subentry_id=subentry_id)
    runtime["climate_entities"] = entities


class RoseTclClimate(ClimateEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_assumed_state = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 16
    _attr_max_temp = 31
    _attr_target_temperature_step = 1
    _attr_hvac_modes = [HVACMode.OFF, *HVAC_TO_TCL]
    _attr_fan_modes = [mode.value for mode in TclFanMode]
    _attr_swing_modes = ["off", "vertical", "horizontal", "both"]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.SWING_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, client, key: str, config: dict) -> None:
        self._client = client
        self.config_key = key
        self._config = config
        self._attr_name = config.get("name", key.replace("_", " ").title())
        self._attr_unique_id = f"rose_climate_{key}"
        self._attr_hvac_mode = HVACMode.OFF
        self._last_active_mode = HVACMode.COOL
        self._attr_target_temperature = float(config.get("temperature", 26))
        self._attr_fan_mode = TclFanMode.AUTO.value
        self._attr_swing_mode = "vertical"
        self._control_listeners: list[Callable[[], None]] = []
        self._extra = {
            "econo": False,
            "health": False,
            "turbo": False,
            "light": True,
            "timer_minutes": 0,
            "aux_heat": False,
        }

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, "platform")},
        }

    @property
    def extra_state_attributes(self):
        return {**self._extra, "last_active_mode": self._last_active_mode}

    def add_control_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._control_listeners.append(listener)

        def remove_listener() -> None:
            if listener in self._control_listeners:
                self._control_listeners.remove(listener)

        return remove_listener

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None:
            return
        if last_state.state in self._attr_hvac_modes:
            self._attr_hvac_mode = HVACMode(last_state.state)
        attributes = last_state.attributes
        last_active_mode = attributes.get("last_active_mode")
        if last_active_mode in HVAC_TO_TCL:
            self._last_active_mode = HVACMode(last_active_mode)
        temperature = attributes.get("temperature")
        if temperature is not None:
            try:
                restored_temperature = float(temperature)
            except (TypeError, ValueError):
                pass
            else:
                if math.isfinite(restored_temperature):
                    self._attr_target_temperature = min(31.0, max(16.0, restored_temperature))
        fan_mode = attributes.get("fan_mode")
        if fan_mode in self._attr_fan_modes:
            self._attr_fan_mode = fan_mode
        swing_mode = attributes.get("swing_mode")
        if swing_mode in self._attr_swing_modes:
            self._attr_swing_mode = swing_mode
        for key, default in self._extra.items():
            value = attributes.get(key)
            if isinstance(default, bool) and isinstance(value, bool):
                self._extra[key] = value
            elif key == "timer_minutes" and value is not None:
                try:
                    self._extra[key] = min(1440, max(0, int(value)))
                except (TypeError, ValueError):
                    pass

    async def _send(self) -> None:
        active_mode = self._last_active_mode if self._attr_hvac_mode == HVACMode.OFF else self._attr_hvac_mode
        state = TclState(
            power=TclPowerState.OFF if self._attr_hvac_mode == HVACMode.OFF else TclPowerState.ON,
            mode=HVAC_TO_TCL[active_mode],
            temperature_c=self._attr_target_temperature,
            fan=TclFanMode(self._attr_fan_mode),
            swing_vertical=self._attr_swing_mode in ("vertical", "both"),
            swing_horizontal=self._attr_swing_mode in ("horizontal", "both"),
            **self._extra,
        )
        signal, carrier_hz, duty_cycle = encode_tcl_ir_signal(state)
        await self._client.signal_tx(
            int(self._config["gpio"]), signal, carrier_hz, duty_cycle,
            int(self._config.get("repeat", 1)), int(self._config.get("repeat_gap_us", 0)),
        )
        self.async_write_ha_state()
        for listener in tuple(self._control_listeners):
            listener()

    async def async_set_hvac_mode(self, hvac_mode):
        if hvac_mode != HVACMode.OFF:
            self._last_active_mode = hvac_mode
        self._attr_hvac_mode = hvac_mode
        await self._send()

    async def async_set_temperature(self, **kwargs):
        self._attr_target_temperature = float(kwargs[ATTR_TEMPERATURE])
        if self._attr_hvac_mode == HVACMode.OFF:
            self._attr_hvac_mode = self._last_active_mode
        await self._send()

    async def async_set_fan_mode(self, fan_mode):
        self._attr_fan_mode = fan_mode
        await self._send()

    async def async_set_swing_mode(self, swing_mode):
        self._attr_swing_mode = swing_mode
        await self._send()

    async def async_turn_on(self):
        await self.async_set_hvac_mode(self._last_active_mode)

    async def async_turn_off(self):
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_send_extended(self, **values):
        self._extra.update({key: value for key, value in values.items() if value is not None})
        await self._send()
