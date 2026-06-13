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

from app.main import app
from app.db.database import Base, engine
from app.services import bridge_service

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
        self._event_cb = None  # captured event callback

    def _capture_cb(self, cb):
        """Store the real event callback so tests can push fake events."""
        self._event_cb = cb

    def push_event(self, event_type: str, data: dict):
        """Push a fake bridge event through the real event callback pipeline."""
        if self._event_cb:
            self._event_cb({"type": event_type, **data})

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
                patch.object(bridge_service, "gpio_config", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "gpio_set", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "gpio_get", new=AsyncMock(return_value=0)),
                patch.object(bridge_service, "adc_sample", new=AsyncMock(return_value=2048)),
                patch.object(bridge_service, "signal_tx", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "signal_rx", new=AsyncMock(return_value=[(1, 100), (0, 200)])),
                patch.object(bridge_service, "signal_exchange", new=AsyncMock(return_value=[(1, 50)])),
                patch.object(bridge_service, "uart_config", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "uart_send", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "uart_read", new=AsyncMock(return_value=b"hello")),
                patch.object(bridge_service, "port_bind", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "port_unbind", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "port_status", new=AsyncMock(return_value={
                    "resource_type": 0, "id": 5, "in_use": True, "mode": 1, "value": 1,
                })),
                patch.object(bridge_service, "ble_enable_pairing", new=AsyncMock(return_value="123456")),
                patch.object(bridge_service, "ble_disable_pairing", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "ble_get_peers", new=AsyncMock(return_value=[
                    {"mac": "AA:BB:CC:DD:EE:FF", "rssi": -45},
                ])),
                patch.object(bridge_service, "ble_start_scan", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "ble_stop_scan", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "ping", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "heartbeat", new=AsyncMock(return_value=0)),
                patch.object(bridge_service, "sync_request", new=AsyncMock(return_value=42)),
                patch.object(bridge_service, "sync_confirm", new=AsyncMock(return_value=True)),
                patch.object(bridge_service, "thread_passthrough", new=AsyncMock(return_value=True)),
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
