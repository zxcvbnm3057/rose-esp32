"""Device Registry grouping rules for Rose config subentries."""
from __future__ import annotations

from .const import (
    CONF_BLE_DEVICES,
    CONF_KEY,
    DOMAIN,
    SUBENTRY_TYPE_BLE,
    SUBENTRY_TYPE_CLIMATE,
    SUBENTRY_TYPE_LIGHT,
    climate_protocol_name,
)


def device_group_specs(entry, ble_states: dict) -> list[dict]:
    """Return one stable Device Registry specification per managed device."""
    specs = []
    for subentry_id, subentry in entry.subentries.items():
        config = dict(subentry.data)
        if subentry.subentry_type == SUBENTRY_TYPE_CLIMATE:
            key = config[CONF_KEY]
            specs.append(
                {
                    "subentry_id": subentry_id,
                    "identifier": (DOMAIN, f"climate_{key}"),
                    "name": config.get("name", key.replace("_", " ").title()),
                    "model": climate_protocol_name(config),
                }
            )
        elif subentry.subentry_type == SUBENTRY_TYPE_LIGHT:
            key = config[CONF_KEY]
            specs.append(
                {
                    "subentry_id": subentry_id,
                    "identifier": (DOMAIN, f"light_{key}"),
                    "name": config.get("name", key.replace("_", " ").title()),
                    "model": "UART light controller",
                }
            )
        elif subentry.subentry_type == SUBENTRY_TYPE_BLE:
            for mac in config.get(CONF_BLE_DEVICES, []):
                specs.append(
                    {
                        "subentry_id": subentry_id,
                        "identifier": (DOMAIN, f"ble_{mac}"),
                        "connection": ("bluetooth", mac),
                        "name": ble_states.get(mac, {}).get("name", mac),
                        "model": "BLE presence device",
                    }
                )
    return specs