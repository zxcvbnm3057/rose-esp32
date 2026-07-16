"""UI configuration flows for Rose."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import RoseApiError, RoseClient
from .const import (
    CLIMATE_PROTOCOL_NAMES,
    CONF_KEY,
    CONF_PLATFORM_URL,
    DOMAIN,
    SUBENTRY_TYPE_CLIMATE,
    SUBENTRY_TYPE_LIGHT,
)

CLIMATE_PROTOCOL_CHOICES = {
    protocol: name
    for protocol, name in CLIMATE_PROTOCOL_NAMES.items()
}


async def _validate_platform(hass, url: str) -> None:
    client = RoseClient(async_get_clientsession(hass), url)
    await client.hardware_config()


class RoseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry):
        return {
            SUBENTRY_TYPE_CLIMATE: RoseClimateSubentryFlow,
            SUBENTRY_TYPE_LIGHT: RoseLightSubentryFlow,
        }

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors = {}
        if user_input is not None:
            url = user_input[CONF_PLATFORM_URL].rstrip("/")
            try:
                await _validate_platform(self.hass, url)
            except RoseApiError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(DOMAIN)
                return self.async_create_entry(title="Rose Platform", data={CONF_PLATFORM_URL: url})
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_PLATFORM_URL, default="http://192.168.137.80:8000"): str}
            ),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            url = user_input[CONF_PLATFORM_URL].rstrip("/")
            try:
                await _validate_platform(self.hass, url)
            except RoseApiError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_PLATFORM_URL: url},
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {vol.Required(CONF_PLATFORM_URL, default=entry.data[CONF_PLATFORM_URL]): str}
            ),
            errors=errors,
        )


class RoseDeviceSubentryFlow(config_entries.ConfigSubentryFlow):
    def _hardware(self) -> dict:
        runtime = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        hardware = runtime.get("hardware", {})
        return hardware if isinstance(hardware, dict) else {}

    @staticmethod
    def _choices(values, current, label) -> dict[int, str]:
        choices = {int(value): label(int(value)) for value in values}
        if current is not None:
            current_value = int(current)
            choices.setdefault(current_value, label(current_value))
        return choices

    def _signal_gpio_choices(self, current=None) -> dict[int, str]:
        pins = self._hardware().get("pins", [])
        gpios = [
            pin["gpio"]
            for pin in pins
            if isinstance(pin, dict)
            and isinstance(pin.get("gpio"), int)
            and pin["gpio"] >= 0
            and not pin.get("reserved", False)
            and isinstance(pin.get("capabilities"), dict)
            and pin["capabilities"].get("signal", False)
        ]
        if not gpios:
            gpios = list(range(31))
        return self._choices(gpios, current, lambda gpio: f"GPIO {gpio}")

    def _uart_choices(self, current=None) -> dict[int, str]:
        capabilities = self._hardware().get("capabilities", {})
        uart_count = capabilities.get("uart_count", 0) if isinstance(capabilities, dict) else 0
        uart_ids = range(max(0, int(uart_count))) if uart_count else range(3)
        return self._choices(uart_ids, current, lambda uart_id: f"UART {uart_id}")

    def _climate_settings_schema(self, current: dict, include_name: bool = False) -> vol.Schema:
        current_gpio = current.get("gpio", 4)
        current_repeat = current.get("repeat", 1)
        schema = {}
        if include_name:
            schema[vol.Required(CONF_NAME, default=current.get(CONF_NAME, ""))] = cv.string
        schema.update({
            vol.Required("gpio", default=current_gpio): vol.In(
                self._signal_gpio_choices(current_gpio)
            ),
            vol.Required("temperature", default=current.get("temperature", 26)): vol.All(
                vol.Coerce(float), vol.Range(min=16, max=31)
            ),
            vol.Required("repeat", default=current_repeat): vol.In(
                self._choices(range(1, 101), current_repeat, str)
            ),
            vol.Required("repeat_gap_us", default=current.get("repeat_gap_us", 0)): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=100000)
            ),
        })
        return vol.Schema(schema)

    def _light_schema(self, current: dict, include_key: bool) -> vol.Schema:
        schema = {}
        if include_key:
            schema[vol.Required(CONF_KEY, default="")] = cv.string
        current_uart_id = current.get("uart_id", 1)
        schema.update(
            {
                vol.Required(CONF_NAME, default=current.get(CONF_NAME, "")): cv.string,
                vol.Required("uart_id", default=current_uart_id): vol.In(
                    self._uart_choices(current_uart_id)
                ),
                vol.Required("on", default=current.get("on", "")): cv.string,
                vol.Required("off", default=current.get("off", "")): cv.string,
            }
        )
        return vol.Schema(schema)

    def _key_error(self, key: str) -> str | None:
        try:
            cv.slug(key)
        except vol.Invalid:
            return "invalid_key"
        if any(
            subentry.data.get(CONF_KEY) == key
            for subentry in self._get_entry().subentries.values()
        ):
            return "key_already_in_use"
        return None


class RoseClimateSubentryFlow(RoseDeviceSubentryFlow):
    def __init__(self) -> None:
        self._pending: dict | None = None

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            if error := self._key_error(user_input[CONF_KEY]):
                errors[CONF_KEY] = error
            else:
                self._pending = dict(user_input)
                return await self.async_step_protocol()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_KEY, default=""): cv.string,
                    vol.Required(CONF_NAME, default=""): cv.string,
                    vol.Required("protocol", default="tcl"): vol.In(CLIMATE_PROTOCOL_CHOICES),
                }
            ),
            errors=errors,
        )

    async def async_step_protocol(self, user_input=None):
        if self._pending is None:
            return await self.async_step_user()
        if user_input is not None:
            data = {**self._pending, **user_input}
            return self.async_create_entry(
                title=data[CONF_NAME],
                data=data,
                unique_id=f"climate_{data[CONF_KEY]}",
            )
        return self.async_show_form(
            step_id="protocol",
            data_schema=self._climate_settings_schema({}),
            description_placeholders={
                "protocol": CLIMATE_PROTOCOL_CHOICES[self._pending["protocol"]]
            },
        )

    async def async_step_reconfigure(self, user_input=None):
        subentry = self._get_reconfigure_subentry()
        current = dict(subentry.data)
        if user_input is not None:
            data = {CONF_KEY: current[CONF_KEY], **user_input}
            return self.async_update_and_abort(
                self._get_entry(), subentry, title=data[CONF_NAME], data=data
            )
        schema = self._climate_settings_schema(current, include_name=True).extend(
            {vol.Required("protocol", default=current.get("protocol", "tcl")): vol.In(CLIMATE_PROTOCOL_CHOICES)}
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema)


class RoseLightSubentryFlow(RoseDeviceSubentryFlow):
    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            if error := self._key_error(user_input[CONF_KEY]):
                errors[CONF_KEY] = error
            else:
                try:
                    bytes.fromhex(user_input["on"])
                    bytes.fromhex(user_input["off"])
                except ValueError:
                    errors["base"] = "invalid_hex"
                else:
                    return self.async_create_entry(
                        title=user_input[CONF_NAME],
                        data=user_input,
                        unique_id=f"light_{user_input[CONF_KEY]}",
                    )
        return self.async_show_form(
            step_id="user",
            data_schema=self._light_schema({}, include_key=True),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None):
        subentry = self._get_reconfigure_subentry()
        current = dict(subentry.data)
        errors = {}
        if user_input is not None:
            try:
                bytes.fromhex(user_input["on"])
                bytes.fromhex(user_input["off"])
            except ValueError:
                errors["base"] = "invalid_hex"
            else:
                data = {CONF_KEY: current[CONF_KEY], **user_input}
                return self.async_update_and_abort(
                    self._get_entry(), subentry, title=data[CONF_NAME], data=data
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._light_schema(current, include_key=False),
            errors=errors,
        )

