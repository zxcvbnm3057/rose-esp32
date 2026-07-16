"""Pure BLE state helpers for the Rose integration."""
from __future__ import annotations


def normalize_mac(value: str) -> str:
    return value.strip().replace("-", ":").lower()


def merge_ble_devices(
    previous: dict,
    names: dict[str, str],
    snapshot: list[dict],
) -> dict:
    """Merge known BLE objects with the current in-range snapshot."""
    devices = {
        normalize_mac(device["mac"]): device
        for device in snapshot
        if isinstance(device, dict) and device.get("mac")
    }
    ble = {normalize_mac(mac): dict(state) for mac, state in previous.items()}
    normalized_names = {normalize_mac(mac): name for mac, name in names.items()}
    for mac in set(ble) | set(normalized_names) | set(devices):
        ble[mac] = {
            "home": mac in devices,
            "rssi": devices.get(mac, {}).get("rssi"),
            "name": normalized_names.get(mac) or ble.get(mac, {}).get("name") or mac,
        }
    return ble
