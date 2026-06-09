"""Test signal endpoints — config GPIO first in real mode.
Hardware setup: GPIO5 ↔ GPIO4 loopback wire for signal tests.

Note: exchange on GPIO5 with GPIO5→GPIO4 loopback will TX on GPIO5
but RX on GPIO5 sees no edges (signal went to GPIO4).  The device
ACKs and captures anyway, returning edge_count=0 — this is valid.
"""
import pytest


@pytest.mark.anyio
async def test_signal_tx(client, mock_bridge, is_real):
    # Configure pin for SIGNAL mode first, then send TX
    if is_real:
        await client.post("/api/v1/port/unbind", json={"resource_type": 0, "id": 5})
        await client.post("/api/v1/gpio/5/config", json={"mode": 4})
    res = await client.post("/api/v1/gpio/5/signal/tx", json={
        "signal": [{"level": 1, "duration_us": 100}, {"level": 0, "duration_us": 200}],
        "delay_us": 0,
    })
    assert res.status_code == 200
    assert res.json()["success"] is True


@pytest.mark.anyio
async def test_signal_rx(client, mock_bridge, is_real):
    # RX on GPIO4: even when no TX is running, the device should
    # ACK the command and return a (possibly empty) capture result.
    if is_real:
        await client.post("/api/v1/gpio/4/config", json={"mode": 4})
    res = await client.post("/api/v1/gpio/4/signal/rx", json={
        "timeout_us": 500000, "max_edges": 100,
    })
    assert res.status_code == 200
    assert res.json()["success"] is True


@pytest.mark.anyio
async def test_signal_exchange(client, mock_bridge, is_real):
    # Exchange: TX then RX on same pin.  With GPIO5→GPIO4 loopback,
    # the RX phase on GPIO5 captures nothing — edge_count=0 is valid.
    if is_real:
        await client.post("/api/v1/gpio/5/config", json={"mode": 4})
    res = await client.post("/api/v1/gpio/5/signal/exchange", json={
        "tx_signal": [{"level": 1, "duration_us": 100}],
        "delay_us": 50, "rx_total_us": 500000, "rx_max_edges": 100,
    })
    assert res.status_code == 200
    assert res.json()["success"] is True


@pytest.mark.anyio
async def test_signal_tx_too_many_edges(client, mock_bridge):
    edges = [{"level": 1, "duration_us": 10}] * 300
    res = await client.post("/api/v1/gpio/5/signal/tx", json={"signal": edges})
    assert res.status_code == 422
