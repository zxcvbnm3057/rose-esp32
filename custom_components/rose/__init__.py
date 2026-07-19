"""Rose Home Assistant integration."""
from __future__ import annotations

from pathlib import Path

import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry

from .client import RoseApiError, RoseClient
from .const import CONF_PLATFORM_URL, DOMAIN, PLATFORMS
from .coordinator import RoseCoordinator

FRONTEND_URL = "/rose_frontend"
FRONTEND_MODULE_URL = f"{FRONTEND_URL}/rose-climate-remote-card.js"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL, str(Path(__file__).parent / "www"), cache_headers=False)]
    )
    add_extra_js_url(hass, FRONTEND_MODULE_URL)
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = RoseClient(async_get_clientsession(hass), entry.data[CONF_PLATFORM_URL])
    try:
        hardware = await client.hardware_config()
    except RoseApiError as exc:
        raise ConfigEntryNotReady(str(exc)) from exc

    coordinator = RoseCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "hardware": hardware,
        "climate_entities": {},
    }
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_start_websocket()

    if not hass.services.has_service(DOMAIN, "send_tcl"):
        async def async_send_tcl(call: ServiceCall) -> None:
            key = call.data["climate"]
            for runtime in hass.data.get(DOMAIN, {}).values():
                entity = runtime.get("climate_entities", {}).get(key)
                if entity is not None:
                    await entity.async_send_extended(
                        econo=call.data.get("econo"),
                        health=call.data.get("health"),
                        turbo=call.data.get("turbo"),
                        light=call.data.get("light"),
                        timer_minutes=call.data.get("timer_minutes"),
                        aux_heat=call.data.get("aux_heat"),
                    )
                    return
            raise HomeAssistantError(f"Unknown Rose climate key: {key}")

        hass.services.async_register(
            DOMAIN,
            "send_tcl",
            async_send_tcl,
            schema=vol.Schema(
                {
                    vol.Required("climate"): cv.slug,
                    vol.Optional("econo"): cv.boolean,
                    vol.Optional("health"): cv.boolean,
                    vol.Optional("turbo"): cv.boolean,
                    vol.Optional("light"): cv.boolean,
                    vol.Optional("timer_minutes"): vol.All(vol.Coerce(int), vol.Range(min=0, max=1440)),
                    vol.Optional("aux_heat"): cv.boolean,
                }
            ),
        )
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await hass.data[DOMAIN][entry.entry_id]["coordinator"].async_stop_websocket()
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "send_tcl")
    return unloaded


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    rose_identifiers = {
        identifier
        for domain, identifier in device_entry.identifiers
        if domain == DOMAIN
    }
    managed_identifiers = {(DOMAIN, "platform")}
    managed_identifiers.update(
        (DOMAIN, identifier)
        for subentry in entry.subentries.values()
        if (identifier := subentry.unique_id) is not None
    )
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator = runtime.get("coordinator")
    ble_devices = (coordinator.data or {}).get("ble", {}) if coordinator else {}
    managed_identifiers.update((DOMAIN, f"ble_{mac}") for mac in ble_devices)
    return (
        bool(rose_identifiers)
        and device_entry.identifiers.isdisjoint(managed_identifiers)
        and all(
            identifier.startswith("ble_")
            for identifier in rose_identifiers
        )
    )
