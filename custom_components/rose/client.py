"""HTTP client for the generic Rose platform API."""
from __future__ import annotations

import base64
import json
from typing import Any

from aiohttp import ClientError, ClientSession


class RoseApiError(RuntimeError):
    """Raised when the Rose platform rejects a request."""


class RoseClient:
    def __init__(self, session: ClientSession, base_url: str) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            async with self._session.request(method, f"{self._base_url}{path}", **kwargs) as response:
                body = await response.json(content_type=None)
                response.raise_for_status()
        except (ClientError, TimeoutError, OSError, ValueError) as exc:
            raise RoseApiError(str(exc)) from exc
        if not isinstance(body, dict):
            raise RoseApiError("Rose platform returned a non-object response")
        if not body.get("success", False):
            raise RoseApiError(str(body.get("error") or "Rose platform request failed"))
        data = body.get("data") or {}
        if not isinstance(data, dict):
            raise RoseApiError("Rose platform returned invalid response data")
        return data

    async def hardware_config(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/hardware/config")

    async def device_status(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/device/status")

    async def ble_in_range(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/v1/ble/in-range")
        devices = data.get("devices", [])
        return [device for device in devices if isinstance(device, dict) and device.get("mac")]

    async def ble_device_names(self) -> dict[str, str]:
        data = await self._request("GET", "/api/v1/ble/device-names")
        return {
            str(item["mac"]).strip().replace("-", ":").lower(): str(item["name"])
            for item in data.get("names", [])
            if isinstance(item, dict) and item.get("mac") and item.get("name")
        }

    async def websocket_messages(self):
        ws_url = self._base_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        async with self._session.ws_connect(f"{ws_url}/ws?role=app", heartbeat=30) as websocket:
            async for message in websocket:
                if message.type.name == "TEXT":
                    try:
                        yield json.loads(message.data)
                    except (TypeError, json.JSONDecodeError):
                        continue

    async def signal_tx(
        self,
        gpio: int,
        signal: list[dict[str, int]],
        carrier_hz: int,
        duty_cycle: float,
        repeat: int = 1,
        repeat_gap_us: int = 0,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/v1/gpio/{gpio}/signal/tx",
            json={
                "signal": signal,
                "carrier_hz": carrier_hz,
                "duty_cycle": duty_cycle,
                "repeat": repeat,
                "repeat_gap_us": repeat_gap_us,
            },
        )

    async def uart_send(self, uart_id: int, hex_command: str) -> dict[str, Any]:
        encoded = base64.b64encode(bytes.fromhex(hex_command)).decode("ascii")
        return await self._request(
            "POST",
            f"/api/v1/uart/{uart_id}/send",
            json={"data_base64": encoded},
        )
