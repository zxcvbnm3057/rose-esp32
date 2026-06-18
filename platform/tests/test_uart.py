"""Test UART endpoints.
Hardware setup: GPIO1 ↔ GPIO3 loopback wire for UART tests.
"""
import asyncio
import base64
import os
import pytest
import httpx

# Match root test UART config (defaults to UART1 with GPIO1↔3)
_UART_ID = int(os.getenv("TEST_UART_ID", "1"))
_UART_TX = int(os.getenv("TEST_UART_TX", "1"))
_UART_RX = int(os.getenv("TEST_UART_RX", "3"))


async def _ensure_uart_configured(client):
    """Configure UART — unbind first (ignore error if not bound), then config."""
    # Try unbind, ignore if not bound
    await client.post(f"/api/v1/port/unbind", json={"resource_type": 1, "id": _UART_ID})
    r = await client.post(f"/api/v1/uart/{_UART_ID}/config", json={
        "baudrate": 115200, "tx_gpio": _UART_TX, "rx_gpio": _UART_RX,
    })
    if r.status_code == 200:
        await asyncio.sleep(0.3)
    return r


@pytest.mark.anyio
async def test_uart_config(client, mock_bridge, is_real):
    """Configure UART — single config call."""
    if is_real:
        res = await _ensure_uart_configured(client)
        assert res.status_code == 200
        assert res.json()["success"] is True
    else:
        res = await client.post(f"/api/v1/uart/{_UART_ID}/config", json={
            "baudrate": 115200, "tx_gpio": _UART_TX, "rx_gpio": _UART_RX,
        })
        assert res.status_code == 200
        assert res.json()["success"] is True


@pytest.mark.anyio
async def test_uart_send(client, mock_bridge, is_real):
    await _ensure_uart_configured(client)
    res = await client.post(f"/api/v1/uart/{_UART_ID}/send", json={"data": "hello"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["data"]["bytes_sent"] == 5


@pytest.mark.anyio
async def test_uart_send_base64(client, mock_bridge, is_real):
    await _ensure_uart_configured(client)
    encoded = base64.b64encode(b"binary").decode()
    res = await client.post(f"/api/v1/uart/{_UART_ID}/send", json={"data_base64": encoded})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["data"]["bytes_sent"] == 6


@pytest.mark.anyio
async def test_uart_send_no_data(client, mock_bridge):
    res = await client.post(f"/api/v1/uart/{_UART_ID}/send", json={})
    assert res.status_code == 400


@pytest.mark.anyio
async def test_uart_read(client, mock_bridge, is_real):
    await _ensure_uart_configured(client)
    if is_real:
        # Send some data first so there's something to read (UART loopback)
        await client.post(f"/api/v1/uart/{_UART_ID}/send", json={"data": "test"})
        await asyncio.sleep(0.3)
    res = await client.get(f"/api/v1/uart/{_UART_ID}/read?length=256")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "data_base64" in data["data"]


@pytest.mark.anyio
async def test_uart_send_rejects_unbound_uart(client, mock_bridge, is_real):
    if is_real:
        pytest.skip("guard assertion is mock-only")
    # Ensure UART is unbound first, then sending must be rejected as NOT_BOUND.
    await client.post(f"/api/v1/port/unbind", json={"resource_type": 1, "id": _UART_ID})
    res = await client.post(f"/api/v1/uart/{_UART_ID}/send", json={"data": "hello"})
    assert res.status_code == 409


@pytest.mark.anyio
async def test_uart_read_rejects_unbound_uart(client, mock_bridge, is_real):
    if is_real:
        pytest.skip("guard assertion is mock-only")
    # Ensure UART is unbound first, then reading must be rejected as NOT_BOUND.
    await client.post(f"/api/v1/port/unbind", json={"resource_type": 1, "id": _UART_ID})
    res = await client.get(f"/api/v1/uart/{_UART_ID}/read?length=256")
    assert res.status_code == 409
