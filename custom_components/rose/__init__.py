"""Rose Home Assistant integration."""
from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .client import RoseApiError, RoseClient
from .const import (
    CONF_BLE_DEVICES,
    CONF_PLATFORM_URL,
    DOMAIN,
    PLATFORMS,
    SUBENTRY_TYPE_BLE,
)
from .coordinator import RoseCoordinator
from .device_groups import prepare_device_registry

FRONTEND_URL = "/rose_frontend"
FRONTEND_MODULE_URL = f"{FRONTEND_URL}/rose-climate-remote-card.js"


def _prepare_device_registry(hass: HomeAssistant, entry: ConfigEntry, coordinator) -> None:
    device_registry = dr.async_get(hass)
    ble_states = (coordinator.data or {}).get("ble", {})
    prepare_device_registry(device_registry, entry, ble_states)


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
    if CONF_BLE_DEVICES not in entry.options and not any(
        subentry.subentry_type == SUBENTRY_TYPE_BLE
        for subentry in entry.subentries.values()
    ):
        entity_registry = er.async_get(hass)
        device_registry = dr.async_get(hass)
        existing_macs = []
        for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
            if entity.domain != "device_tracker" or entity.device_id is None:
                continue
            device = device_registry.async_get(entity.device_id)
            if device is None:
                continue
            existing_macs.extend(
                identifier.removeprefix("ble_")
                for domain, identifier in device.identifiers
                if domain == DOMAIN and identifier.startswith("ble_")
            )
        if existing_macs:
            hass.config_entries.async_update_entry(
                entry,
                options={**entry.options, CONF_BLE_DEVICES: sorted(set(existing_macs))},
            )
    legacy_ble_devices = entry.options.get(CONF_BLE_DEVICES, [])
    if legacy_ble_devices and not any(
        subentry.subentry_type == SUBENTRY_TYPE_BLE
        for subentry in entry.subentries.values()
    ):
        ble_subentry = ConfigSubentry(
            data=MappingProxyType({CONF_BLE_DEVICES: list(legacy_ble_devices)}),
            subentry_type=SUBENTRY_TYPE_BLE,
            title="BLE devices",
            unique_id="ble_devices",
        )
        hass.config_entries.async_add_subentry(
            entry,
            ble_subentry,
        )
        entity_registry = er.async_get(hass)
        device_registry = dr.async_get(hass)
        selected_unique_ids = {
            f"rose_ble_{mac.replace(':', '')}"
            for mac in legacy_ble_devices
        }
        for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
            if entity.unique_id not in selected_unique_ids:
                continue
            entity_registry.async_update_entity(
                entity.entity_id,
                config_entry_id=entry.entry_id,
                config_subentry_id=ble_subentry.subentry_id,
            )
        options = dict(entry.options)
        options.pop(CONF_BLE_DEVICES, None)
        hass.config_entries.async_update_entry(entry, options=options)
    _prepare_device_registry(hass, entry, coordinator)
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
    managed_identifiers.update(
        (DOMAIN, f"ble_{mac}")
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_TYPE_BLE
        for mac in subentry.data.get(CONF_BLE_DEVICES, [])
    )
    return (
        bool(rose_identifiers)
        and device_entry.identifiers.isdisjoint(managed_identifiers)
        and all(
            identifier.startswith("ble_")
            for identifier in rose_identifiers
        )
    )
