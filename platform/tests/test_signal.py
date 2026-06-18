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
        "carrier_hz": 38000,
        "duty_cycle": 0.33,
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
        "delay_us": 50, "carrier_hz": 38000, "duty_cycle": 0.33, "rx_total_us": 500000, "rx_max_edges": 100,
    })
    assert res.status_code == 200
    assert res.json()["success"] is True


@pytest.mark.anyio
async def test_signal_tx_invalid_carrier_range(client, mock_bridge):
    res = await client.post("/api/v1/gpio/5/signal/tx", json={
        "signal": [{"level": 1, "duration_us": 100}],
        "carrier_hz": 600000,
        "duty_cycle": 0.5,
    })
    assert res.status_code == 422


@pytest.mark.anyio
async def test_signal_tx_too_many_edges(client, mock_bridge):
    edges = [{"level": 1, "duration_us": 10}] * 300
    res = await client.post("/api/v1/gpio/5/signal/tx", json={"signal": edges})
    assert res.status_code == 422


# ── resolution 透传（软件 glitch-merge，在 bridge client 完成）──────────
# 固件始终最细采集；backend 不做 clamp，原样把 resolution(预设名/微秒/None)
# 透传给 client 的软件层。

@pytest.mark.anyio
@pytest.mark.parametrize("requested", [None, 1, 10, 254, 1000, "exact", "fine", "normal", "coarse"])
async def test_signal_exchange_resolution_passthrough(requested, is_real):
    """backend.signal_exchange 应把 resolution 原样透传给 client.exchange_signals。"""
    if is_real:
        pytest.skip("纯透传逻辑，mock 专用")
    from unittest.mock import patch, MagicMock
    from src.services import bridge_service

    fake_client = MagicMock()
    fake_client.exchange_signals.return_value = []
    with patch.object(bridge_service, "get_client", return_value=fake_client):
        await bridge_service.signal_exchange(
            gpio=5,
            tx_signal=[{"level": 1, "duration_us": 100}],
            delay_us=0,
            rx_total_us=500000,
            rx_max_edges=100,
            carrier_hz=38000,
            duty_cycle=0.33,
            resolution=requested,
        )
    # exchange_signals(gpio, tx, delay_us, carrier_hz, duty_cycle, rx_total_us, rx_max_edges, resolution)
    args = fake_client.exchange_signals.call_args.args
    assert args[3] == 38000
    assert args[4] == 0.33
    assert args[-1] == requested  # 无 clamp / 无转换


@pytest.mark.anyio
@pytest.mark.parametrize("requested", [None, 20, "normal"])
async def test_signal_rx_resolution_passthrough(requested, is_real):
    """backend.signal_rx 同样把 resolution 透传给 client.receive_signal。"""
    if is_real:
        pytest.skip("纯透传逻辑，mock 专用")
    from unittest.mock import patch, MagicMock
    from src.services import bridge_service

    fake_client = MagicMock()
    fake_client.receive_signal.return_value = []
    with patch.object(bridge_service, "get_client", return_value=fake_client):
        await bridge_service.signal_rx(gpio=4, timeout_us=500000, max_edges=100, resolution=requested)
    args = fake_client.receive_signal.call_args.args
    assert args[-1] == requested


@pytest.mark.anyio
async def test_signal_resolutions_endpoint(client):
    """GET /gpio/signal/resolutions 列出软件分辨率预设。"""
    res = await client.get("/api/v1/gpio/signal/resolutions")
    assert res.status_code == 200
    data = res.json()["data"]
    names = {p["name"] for p in data["presets"]}
    assert {"exact", "fine", "normal", "coarse"} <= names
    assert data["default"] == "exact"


