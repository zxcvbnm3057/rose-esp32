"""Test fixtures — mock bridge by default, USE_REAL_DEVICE=1 for real ESP32."""
from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.main import app
from src.db.database import Base, engine
from src.services import bridge_service

USE_REAL = os.environ.get("USE_REAL_DEVICE", "").strip().lower() in ("1", "true", "yes")


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
async def client():
    if USE_REAL:
        # Real mode: test against the running uvicorn server (which has real bridge)
        async with AsyncClient(base_url="http://127.0.0.1:8000") as c:
            yield c
    else:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
def is_real():
    return USE_REAL


class _MockBridge:
    def __init__(self):
        self.connected = True
        # Mirrors the real bridge client's last_error (firmware IOT_ERR_* code).
        # Set by command mocks on failure so the API can map it to a precise
        # HTTP status (e.g. NOT_BOUND -> 409). None == unknown/success.
        self._last_error = None
        self._event_cb = None  # captured event callback
        self._gpio_state = {
            5: {"resource_type": 0, "id": 5, "in_use": True, "mode": 1, "pull": 0, "edge": 0, "value": 0, "owner": 0, "adc_raw": 0, "adc_mv": 0},
            2: {"resource_type": 0, "id": 2, "in_use": True, "mode": 3, "pull": 0, "edge": 0, "value": 0, "owner": 0, "adc_raw": 2048, "adc_mv": round(2048 / 4095 * 3300, 1)},
        }
        self._uart_state = {
            # UART0 is the device's default log output port and is never used
            # for data tests. UART1 is the data port and is pre-bound so send
            # tests have a ready target (GPIO4=TX, GPIO6=RX).
            1: {"uart_id": 1, "bound": True, "baudrate": 115200, "tx_gpio": 4, "rx_gpio": 6}
        }

    def _capture_cb(self, cb):
        """Store the real event callback so tests can push fake events."""
        self._event_cb = cb

    def push_event(self, event_type: str, data: dict):
        """Push a fake bridge event through the real event callback pipeline."""
        if self._event_cb:
            self._event_cb({"type": event_type, **data})

    async def _gpio_config(self, gpio: int, mode: int, pull: int = 0, edge: int = 0):
        for uart in self._uart_state.values():
            if uart["bound"] and gpio in (uart["tx_gpio"], uart["rx_gpio"]):
                return False
        state = self._gpio_state.setdefault(gpio, {
            "resource_type": 0, "id": gpio, "in_use": True, "mode": mode, "pull": pull,
            "edge": edge, "value": 0, "owner": 0, "adc_raw": 0, "adc_mv": 0,
        })
        state.update({"mode": mode, "pull": pull, "edge": edge, "in_use": True})
        return True

    async def _gpio_set(self, gpio: int, value: int):
        state = self._gpio_state.get(gpio)
        if state is None or not state.get("in_use") or state.get("mode") not in (1, 5):
            return False
        for uart in self._uart_state.values():
            if uart["bound"] and gpio in (uart["tx_gpio"], uart["rx_gpio"]):
                return False
        state["value"] = value
        state["mode"] = state.get("mode", 1)
        state["in_use"] = True
        return True

    async def _gpio_get(self, gpio: int):
        state = self._gpio_state.setdefault(gpio, {
            "resource_type": 0, "id": gpio, "in_use": False, "mode": 0xFF, "pull": 0,
            "edge": 0, "value": 0, "owner": 0, "adc_raw": 0, "adc_mv": 0,
        })
        return state.get("value", 0)

    async def _adc_sample(self, gpio: int, samples: int = 1):
        state = self._gpio_state.setdefault(gpio, {
            "resource_type": 0, "id": gpio, "in_use": True, "mode": 3, "pull": 0,
            "edge": 0, "value": 0, "owner": 0, "adc_raw": 2048, "adc_mv": round(2048 / 4095 * 3300, 1),
        })
        state["mode"] = 3
        state["adc_mv"] = round(state.get("adc_raw", 0) / 4095 * 3300, 1)
        return state.get("adc_raw", 0)

    async def _port_status(self, resource_type: int, id: int):
        if resource_type == 1:
            uart = self._uart_state.get(id, {"bound": False, "baudrate": 0})
            return {"resource_type": 1, "id": id, "in_use": uart["bound"], "mode": None, "pull": None, "edge": None, "value": uart["baudrate"] & 0xFF if uart["bound"] else None, "owner": 0, "adc_raw": None, "adc_mv": None}
        if resource_type != 0:
            return {"resource_type": resource_type, "id": id, "in_use": False, "mode": None, "pull": None, "edge": None, "value": None, "owner": 0, "adc_raw": None, "adc_mv": None}
        state = self._gpio_state.setdefault(id, {
            "resource_type": 0, "id": id, "in_use": False, "mode": 0xFF, "pull": 0,
            "edge": 0, "value": 0, "owner": 0, "adc_raw": 0, "adc_mv": 0,
        })
        return dict(state)

    async def _port_unbind(self, resource_type: int, id: int):
        if resource_type == 0:
            state = self._gpio_state.setdefault(id, {
                "resource_type": 0, "id": id, "in_use": False, "mode": 0xFF, "pull": 0,
                "edge": 0, "value": 0, "owner": 0, "adc_raw": 0, "adc_mv": 0,
            })
            state.update({"in_use": False, "mode": 0xFF, "owner": 0})
            for uart in self._uart_state.values():
                if uart["bound"] and id in (uart["tx_gpio"], uart["rx_gpio"]):
                    uart["bound"] = False
                    uart["baudrate"] = 0
                    uart["tx_gpio"] = 0xFF
                    uart["rx_gpio"] = 0xFF
            return True
        if resource_type == 1:
            uart = self._uart_state.setdefault(id, {"uart_id": id, "bound": False, "baudrate": 0, "tx_gpio": 0xFF, "rx_gpio": 0xFF})
            tx_gpio = uart.get("tx_gpio", 0xFF)
            rx_gpio = uart.get("rx_gpio", 0xFF)
            uart.update({"bound": False, "baudrate": 0, "tx_gpio": 0xFF, "rx_gpio": 0xFF})
            for gpio in (tx_gpio, rx_gpio):
                if gpio != 0xFF and gpio in self._gpio_state:
                    self._gpio_state[gpio].update({"in_use": False, "mode": 0xFF, "owner": 0})
            return True
        return True

    async def _uart_config(self, uart_id: int, baudrate: int, tx_gpio: int, rx_gpio: int, data_bits: int = 8, parity: int = 0, stop_bits: int = 1):
        if tx_gpio == rx_gpio:
            return False
        for gpio in (tx_gpio, rx_gpio):
            gpio_state = self._gpio_state.get(gpio)
            if gpio_state and gpio_state.get("in_use") and gpio_state.get("mode") in (1, 5):
                return False
        self._uart_state[uart_id] = {
            "uart_id": uart_id,
            "bound": True,
            "baudrate": baudrate,
            "tx_gpio": tx_gpio,
            "rx_gpio": rx_gpio,
        }
        for gpio in (tx_gpio, rx_gpio):
            self._gpio_state[gpio] = {
                "resource_type": 0, "id": gpio, "in_use": True, "mode": 0, "pull": 0, "edge": 0,
                "value": self._gpio_state.get(gpio, {}).get("value", 0), "owner": uart_id + 1, "adc_raw": 0, "adc_mv": 0,
            }
        return True

    async def _uart_send(self, uart_id: int, data: bytes):
        uart = self._uart_state.get(uart_id)
        if not uart or not uart.get("bound"):
            self._last_error = 9  # IOT_ERR_NOT_BOUND
            return False
        self._last_error = None
        return True

    async def _uart_read(self, uart_id: int, length: int = 256):
        uart = self._uart_state.get(uart_id)
        if not uart or not uart.get("bound"):
            self._last_error = 9  # IOT_ERR_NOT_BOUND
            return None
        self._last_error = None
        return b"hello"

    def _get_last_error(self):
        return self._last_error

    def install(self):
        # Always mock infrastructure — prevent duplicate TCP listener
        self._infra = [
            patch.object(bridge_service, "start_bridge", new=AsyncMock()),
            patch.object(bridge_service, "stop_bridge", new=AsyncMock()),
            patch.object(bridge_service, "set_event_callback", side_effect=self._capture_cb),
            patch.object(bridge_service, "is_connected", return_value=USE_REAL),  # true in real mode
        ]
        for p in self._infra:
            p.start()

        if USE_REAL:
            self._mocks = []
        else:
            self._mocks = [
                patch.object(bridge_service, "is_connected", return_value=True),
                patch.object(bridge_service, "gpio_config", new=AsyncMock(side_effect=self._gpio_config)),
                patch.object(bridge_service, "gpio_set", new=AsyncMock(side_effect=self._gpio_set)),
                patch.object(bridge_service, "gpio_get", new=AsyncMock(side_effect=self._gpio_get)),
                patch.object(bridge_service, "adc_sample", new=AsyncMock(side_effect=self._adc_sample)),
                patch.object(bridge_service, "signal_tx", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "signal_rx", new=AsyncMock(return_value=[(1, 100), (0, 200)])),
                patch.object(bridge_service, "signal_exchange", new=AsyncMock(return_value=[(1, 50)])),
                patch.object(bridge_service, "uart_config", new=AsyncMock(side_effect=self._uart_config)),
                patch.object(bridge_service, "uart_send", new=AsyncMock(side_effect=self._uart_send)),
                patch.object(bridge_service, "uart_read", new=AsyncMock(side_effect=self._uart_read)),
                patch.object(bridge_service, "port_bind", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "port_unbind", new=AsyncMock(side_effect=self._port_unbind)),
                patch.object(bridge_service, "port_status", new=AsyncMock(side_effect=self._port_status)),
                patch.object(bridge_service, "ble_enable_pairing", new=AsyncMock(return_value="123456")),
                patch.object(bridge_service, "ble_disable_pairing", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "ble_get_in_range", new=AsyncMock(return_value=[
                    {"mac": "AA:BB:CC:DD:EE:FF", "rssi": -45},
                ])),
                patch.object(bridge_service, "ble_start_scan", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "ble_stop_scan", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "ping", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "heartbeat", new=AsyncMock(return_value=0)),
                patch.object(bridge_service, "sync_request", new=AsyncMock(return_value=42)),
                patch.object(bridge_service, "sync_confirm", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "thread_passthrough", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "get_last_error", side_effect=self._get_last_error),
            ]
        for p in self._mocks:
            p.start()

    def uninstall(self):
        for p in self._mocks:
            p.stop()
        for p in self._infra:
            p.stop()


@pytest.fixture
def mock_bridge():
    m = _MockBridge()
    m.install()
    yield m
    m.uninstall()
