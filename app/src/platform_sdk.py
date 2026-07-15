"""Platform REST and WebSocket wrapper for app-safe APIs."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from .config import settings
from .models import AppEvent, EventSource

logger = logging.getLogger(__name__)

EventCallback = Callable[[AppEvent], Awaitable[None]]


class PlatformApiError(RuntimeError):
    pass


class PlatformClient:
    """Unified wrapper for app-allowed platform REST and WS methods."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(base_url=settings.platform_base_url, timeout=settings.http_timeout_s)
        self._ws_task: asyncio.Task[None] | None = None
        self._running = False

    async def start_ws_listener(self, callback: EventCallback) -> None:
        if self._ws_task and not self._ws_task.done():
            return
        self._running = True
        self._ws_task = asyncio.create_task(self._ws_loop(callback))

    async def stop(self) -> None:
        self._running = False
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        await self._http.aclose()

    async def _ws_loop(self, callback: EventCallback) -> None:
        while self._running:
            try:
                async with websockets.connect(settings.platform_ws_url) as websocket:
                    logger.info("Connected to platform websocket")
                    async for raw in self._iter_ws_messages(websocket):
                        await callback(
                            AppEvent(
                                event_type=raw.get("type", "unknown"),
                                source=EventSource.PLATFORM_WS,
                                payload=raw,
                            )
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Platform websocket loop failed; retrying")
                await asyncio.sleep(settings.reconnect_delay_s)

    async def _iter_ws_messages(self, websocket: Any) -> AsyncIterator[dict[str, Any]]:
        while True:
            try:
                raw = await websocket.recv()
            except ConnectionClosed:
                break
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Discarding non-JSON websocket message: %r", raw)

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        logger.warning(f"Platform API request: {method} {path} {kwargs}")
        response = await self._http.request(method, path, **kwargs)
        response.raise_for_status()
        body = response.json()
        if not body.get("success", False):
            raise PlatformApiError(body.get("error") or f"Platform API failed: {path}")
        return body.get("data") or {}

    async def get_hardware_config(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/hardware/config")

    async def gpio_get(self, gpio: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/v1/gpio/{gpio}/get")

    async def gpio_adc(self, gpio: int, samples: int = 1) -> dict[str, Any]:
        return await self._request("POST", f"/api/v1/gpio/{gpio}/adc", json={"samples": samples})

    async def signal_tx(
        self,
        gpio: int,
        signal: list[dict[str, int]],
        delay_us: int = 0,
        carrier_hz: int = 0,
        duty_cycle: float = 0.5,
        repeat: int = 1,
        repeat_gap_us: int = 0,
    ) -> dict[str, Any]:
        logger.debug("Transmitting signal on GPIO%d: %d edges, delay %dus, carrier %dHz duty %.2f",
                     gpio, len(signal), delay_us, carrier_hz, duty_cycle)
        return await self._request(
            "POST",
            f"/api/v1/gpio/{gpio}/signal/tx",
            json={
                "signal": signal,
                "delay_us": delay_us,
                "carrier_hz": carrier_hz,
                "duty_cycle": duty_cycle,
                "repeat": repeat,
                "repeat_gap_us": repeat_gap_us,
            },
        )

    async def signal_rx(
        self,
        gpio: int,
        timeout_us: int,
        max_edges: int,
        resolution: int | str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/v1/gpio/{gpio}/signal/rx",
            json={"timeout_us": timeout_us, "max_edges": max_edges, "resolution": resolution},
        )

    async def signal_exchange(
        self,
        gpio: int,
        tx_signal: list[dict[str, int]],
        delay_us: int,
        carrier_hz: int,
        duty_cycle: float,
        rx_total_us: int,
        rx_max_edges: int,
        resolution: int | str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/v1/gpio/{gpio}/signal/exchange",
            json={
                "tx_signal": tx_signal,
                "delay_us": delay_us,
                "carrier_hz": carrier_hz,
                "duty_cycle": duty_cycle,
                "rx_total_us": rx_total_us,
                "rx_max_edges": rx_max_edges,
                "resolution": resolution,
            },
        )

    async def get_signal_resolutions(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/gpio/signal/resolutions")

    async def uart_send(
        self,
        uart_id: int,
        *,
        data: str | None = None,
        encoding: str = "utf-8",
        data_base64: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if data_base64 is not None:
            payload["data_base64"] = data_base64
        else:
            payload["data"] = data or ""
            payload["encoding"] = encoding
        return await self._request("POST", f"/api/v1/uart/{uart_id}/send", json=payload)

    async def ble_get_in_range(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/ble/in-range")

    async def ble_get_device_names(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/ble/device-names")

    async def list_commands(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/cmds")

    async def get_command(self, slug: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/v1/cmds/{slug}")

    async def execute_command(self, slug: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("POST", f"/api/v1/cmds/{slug}/execute", json={"params": params or {}})

    async def thread_passthrough(self, device_id: int, correlation_id: int, payload: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/v1/thread/passthrough",
            json={"device_id": device_id, "correlation_id": correlation_id, "payload": payload},
        )
