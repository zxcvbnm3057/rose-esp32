"""State coordinator for Rose platform connectivity."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
import logging

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import RoseApiError, RoseClient
from .const import EVENT_BLE_PRESENCE

LOGGER = logging.getLogger(__name__)
WS_RECONNECT_MAX_DELAY = 30


def normalize_mac(value: str) -> str:
    return value.strip().replace("-", ":").lower()


def next_reconnect_delay(current: int) -> int:
    return min(current * 2, WS_RECONNECT_MAX_DELAY)


def connection_changed(data: dict | None, connected: bool) -> dict:
    updated = dict(data or {})
    updated["connected"] = connected
    if not connected:
        updated["ble"] = {
            mac: {**state, "home": False, "rssi": None}
            for mac, state in updated.get("ble", {}).items()
        }
    return updated


class RoseCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass, client: RoseClient) -> None:
        super().__init__(hass, logger=LOGGER, name="Rose", update_interval=timedelta(seconds=15))
        self.client = client
        self._ble_discovered_callbacks: list[Callable[[str], None]] = []
        self._ws_task: asyncio.Task | None = None
        self._received_ble_snapshot = False

    def async_add_ble_discovered_callback(self, callback: Callable[[str], None]) -> Callable[[], None]:
        self._ble_discovered_callbacks.append(callback)

        def remove_callback() -> None:
            if callback in self._ble_discovered_callbacks:
                self._ble_discovered_callbacks.remove(callback)

        return remove_callback

    async def _async_update_data(self) -> dict:
        try:
            status = await self.client.device_status()
            previous = (self.data or {}).get("ble", {})
            ble = {mac: dict(state) for mac, state in previous.items()}
            if status.get("connected"):
                names = await self.client.ble_device_names()
                snapshot = {
                    normalize_mac(device["mac"]): device
                    for device in await self.client.ble_in_range()
                }
                for mac in set(ble) | set(names) | set(snapshot):
                    ble[mac] = {
                        "home": mac in snapshot,
                        "rssi": snapshot.get(mac, {}).get("rssi"),
                        "name": names.get(mac) or ble.get(mac, {}).get("name") or mac,
                    }
            return {**status, "ble": ble}
        except RoseApiError as exc:
            raise UpdateFailed(str(exc)) from exc

    async def async_start_websocket(self) -> None:
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = self.hass.async_create_background_task(
                self._websocket_loop(), "rose_ble_websocket"
            )

    async def async_stop_websocket(self) -> None:
        if self._ws_task is not None:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None

    async def _websocket_loop(self) -> None:
        reconnect_delay = 1
        while True:
            try:
                async for event in self.client.websocket_messages():
                    reconnect_delay = 1
                    self._handle_ble_event(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.debug("Rose WebSocket disconnected: %s", exc)
            await self.async_request_refresh()
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = next_reconnect_delay(reconnect_delay)

    def _handle_ble_event(self, event: dict) -> None:
        event_type = event.get("type")
        if event_type == "connection_change":
            connected = bool(event.get("connected"))
            self.async_set_updated_data(connection_changed(self.data, connected))
            self.hass.async_create_task(self.async_request_refresh())
            return
        if event_type == "ble_in_range_list":
            devices = {
                normalize_mac(device["mac"]): device
                for device in event.get("devices", [])
            }
            known_macs = set((self.data or {}).get("ble", {})) | set(devices)
            for mac in known_macs:
                self._set_ble_state(
                    mac,
                    mac in devices,
                    devices.get(mac, {}).get("rssi"),
                    self._received_ble_snapshot,
                )
            self._received_ble_snapshot = True
            return
        if event_type not in ("ble_device_in_range", "ble_device_out_of_range", "ble_rssi"):
            return
        mac = normalize_mac(str(event.get("mac", "")))
        if not mac:
            return
        previous = (self.data or {}).get("ble", {}).get(mac, {})
        home = event_type != "ble_device_out_of_range" if event_type != "ble_rssi" else bool(previous.get("home"))
        rssi = event.get("rssi", previous.get("rssi"))
        self._set_ble_state(mac, home, rssi, event_type != "ble_rssi")

    def _set_ble_state(self, mac: str, home: bool, rssi: int | None, fire_event: bool) -> None:
        data = dict(self.data or {})
        ble = {key: dict(value) for key, value in data.get("ble", {}).items()}
        is_new = mac not in ble
        previous_home = bool(ble.get(mac, {}).get("home"))
        ble[mac] = {
            "home": home,
            "rssi": rssi,
            "name": ble.get(mac, {}).get("name", mac),
        }
        data["ble"] = ble
        self.async_set_updated_data(data)
        if is_new:
            for callback in tuple(self._ble_discovered_callbacks):
                callback(mac)
        if fire_event and home != previous_home:
            self.hass.bus.async_fire(
                EVENT_BLE_PRESENCE,
                {
                    "name": ble[mac]["name"],
                    "mac": mac,
                    "home": home,
                    "rssi": rssi,
                },
            )
