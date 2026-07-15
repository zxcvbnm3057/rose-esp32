"""UI configuration flows for Rose."""
from __future__ import annotations

from copy import deepcopy

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import RoseApiError, RoseClient
from .const import CONF_CLIMATES, CONF_LIGHTS, CONF_PLATFORM_URL, DOMAIN

CONF_KEY = "key"


async def _validate_platform(hass, url: str) -> None:
    client = RoseClient(async_get_clientsession(hass), url)
    await client.hardware_config()


class RoseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

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

    @staticmethod
    def async_get_options_flow(config_entry):
        return RoseOptionsFlow()

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


class RoseOptionsFlow(config_entries.OptionsFlow):
    def __init__(self) -> None:
        self._options: dict | None = None
        self._selected_key: str | None = None

    def _ensure_options(self) -> dict:
        if self._options is None:
            self._options = deepcopy(dict(self.config_entry.options))
        return self._options

    async def async_step_init(self, user_input=None):
        self._ensure_options()
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "add_climate",
                "edit_climate",
                "delete_climate",
                "add_light",
                "edit_light",
                "delete_light",
            ],
        )

    async def async_step_add_climate(self, user_input=None):
        return await self._climate_form("add_climate", user_input)

    async def async_step_edit_climate(self, user_input=None):
        return await self._select_device(CONF_CLIMATES, "edit_climate", "climate_form", user_input)

    async def async_step_climate_form(self, user_input=None):
        return await self._climate_form("climate_form", user_input, self._selected_key)

    async def async_step_delete_climate(self, user_input=None):
        return await self._delete_device(CONF_CLIMATES, "delete_climate", user_input)

    async def async_step_add_light(self, user_input=None):
        return await self._light_form("add_light", user_input)

    async def async_step_edit_light(self, user_input=None):
        return await self._select_device(CONF_LIGHTS, "edit_light", "light_form", user_input)

    async def async_step_light_form(self, user_input=None):
        return await self._light_form("light_form", user_input, self._selected_key)

    async def async_step_delete_light(self, user_input=None):
        return await self._delete_device(CONF_LIGHTS, "delete_light", user_input)

    async def _climate_form(self, step_id: str, user_input, existing_key: str | None = None):
        devices = self._ensure_options().setdefault(CONF_CLIMATES, {})
        current = devices.get(existing_key, {})
        errors = {}
        if user_input is not None:
            key = existing_key or user_input.pop(CONF_KEY)
            if existing_key is None and key in devices:
                errors[CONF_KEY] = "already_exists"
            else:
                devices[key] = {"protocol": "tcl", **user_input}
                return self.async_create_entry(title="", data=self._options)
        schema = {}
        if existing_key is None:
            schema[vol.Required(CONF_KEY, default="")] = cv.slug
        schema.update(
            {
                vol.Required(CONF_NAME, default=current.get(CONF_NAME, "")): cv.string,
                vol.Required("gpio", default=current.get("gpio", 4)): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=30)
                ),
                vol.Required("temperature", default=current.get("temperature", 26)): vol.All(
                    vol.Coerce(float), vol.Range(min=16, max=31)
                ),
                vol.Required("repeat", default=current.get("repeat", 1)): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=100)
                ),
                vol.Required("repeat_gap_us", default=current.get("repeat_gap_us", 0)): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=100000)
                ),
            }
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(schema),
            errors=errors,
        )

    async def _light_form(self, step_id: str, user_input, existing_key: str | None = None):
        devices = self._ensure_options().setdefault(CONF_LIGHTS, {})
        current = devices.get(existing_key, {})
        errors = {}
        if user_input is not None:
            key = existing_key or user_input.pop(CONF_KEY)
            if existing_key is None and key in devices:
                errors[CONF_KEY] = "already_exists"
            else:
                try:
                    bytes.fromhex(user_input["on"])
                    bytes.fromhex(user_input["off"])
                except ValueError:
                    errors["base"] = "invalid_hex"
                else:
                    devices[key] = user_input
                    return self.async_create_entry(title="", data=self._options)
        schema = {}
        if existing_key is None:
            schema[vol.Required(CONF_KEY, default="")] = cv.slug
        schema.update(
            {
                vol.Required(CONF_NAME, default=current.get(CONF_NAME, "")): cv.string,
                vol.Required("uart_id", default=current.get("uart_id", 1)): cv.non_negative_int,
                vol.Required("on", default=current.get("on", "")): cv.string,
                vol.Required("off", default=current.get("off", "")): cv.string,
            }
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(schema),
            errors=errors,
        )

    async def _select_device(self, section: str, step_id: str, next_step: str, user_input):
        devices = self._ensure_options().get(section, {})
        if not devices:
            return self.async_abort(reason="no_devices")
        if user_input is not None:
            self._selected_key = user_input[CONF_KEY]
            return await getattr(self, f"async_step_{next_step}")()
        choices = {key: config.get(CONF_NAME) or key for key, config in devices.items()}
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({vol.Required(CONF_KEY): vol.In(choices)}),
        )

    async def _delete_device(self, section: str, step_id: str, user_input):
        devices = self._ensure_options().get(section, {})
        if not devices:
            return self.async_abort(reason="no_devices")
        if user_input is not None:
            devices.pop(user_input[CONF_KEY], None)
            return self.async_create_entry(title="", data=self._options)
        choices = {key: config.get(CONF_NAME) or key for key, config in devices.items()}
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({vol.Required(CONF_KEY): vol.In(choices)}),
        )
