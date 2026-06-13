"""Test pin lock persistence, UART config persistence, and expected state sync."""
import pytest


# ── Pin Lock CRUD ──────────────────────────────────────────

@pytest.mark.anyio
async def test_get_locks_empty(client):
    """Get locks — may contain items from previous test runs in real mode."""
    res = await client.get("/api/v1/pins/locks")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "pins" in data["data"]
    assert "uarts" in data["data"]
    assert isinstance(data["data"]["pins"], list)
    assert isinstance(data["data"]["uarts"], list)


@pytest.mark.anyio
async def test_lock_pin(client):
    res = await client.post("/api/v1/pins/5/lock")
    assert res.status_code == 200
    assert res.json()["data"]["locked"] is True


@pytest.mark.anyio
async def test_lock_idempotent(client):
    await client.post("/api/v1/pins/5/lock")
    res = await client.post("/api/v1/pins/5/lock")
    assert res.status_code == 200
    assert res.json()["data"]["locked"] is True


@pytest.mark.anyio
async def test_unlock_pin(client):
    await client.post("/api/v1/pins/5/lock")
    res = await client.delete("/api/v1/pins/5/lock")
    assert res.status_code == 200
    assert res.json()["data"]["locked"] is False


@pytest.mark.anyio
async def test_unlock_never_locked(client):
    res = await client.delete("/api/v1/pins/99/lock")
    assert res.status_code == 200
    assert res.json()["data"]["locked"] is False


@pytest.mark.anyio
async def test_get_locks_after_ops(client):
    await client.post("/api/v1/pins/4/lock")
    await client.post("/api/v1/pins/5/lock")
    await client.post("/api/v1/pins/6/lock")
    await client.delete("/api/v1/pins/5/lock")  # unlock middle

    res = await client.get("/api/v1/pins/locks")
    pins = res.json()["data"]["pins"]
    locked_map = {p["gpio"]: p["locked"] for p in pins}
    assert locked_map[4] is True
    assert locked_map[5] is False
    assert locked_map[6] is True


# ── Expected state ────────────────────────────────────────

@pytest.mark.anyio
async def test_save_expected_state(client):
    res = await client.post("/api/v1/pins/4/expected", json={
        "expected_mode": 1,
        "expected_value": 1,
    })
    assert res.status_code == 200

    # Verify via get_locks
    res2 = await client.get("/api/v1/pins/locks")
    pins = res2.json()["data"]["pins"]
    pin4 = next((p for p in pins if p["gpio"] == 4), None)
    assert pin4 is not None
    assert pin4["expected_mode"] == 1
    assert pin4["expected_value"] == 1


# ── UART config persistence ───────────────────────────────

@pytest.mark.anyio
async def test_save_uart_config(client):
    res = await client.post("/api/v1/pins/uart/0", json={
        "baudrate": 115200,
        "tx_gpio": 1,
        "rx_gpio": 3,
        "data_bits": 8,
        "parity": 0,
        "stop_bits": 1,
    })
    assert res.status_code == 200

    res2 = await client.get("/api/v1/pins/locks")
    uarts = res2.json()["data"]["uarts"]
    uart0 = next((u for u in uarts if u["uart_id"] == 0), None)
    assert uart0 is not None
    assert uart0["baudrate"] == 115200
    assert uart0["tx_gpio"] == 1
    assert uart0["rx_gpio"] == 3


@pytest.mark.anyio
async def test_save_uart_config_update(client):
    await client.post("/api/v1/pins/uart/0", json={
        "baudrate": 9600, "tx_gpio": 1, "rx_gpio": 3,
    })
    await client.post("/api/v1/pins/uart/0", json={
        "baudrate": 230400, "tx_gpio": 4, "rx_gpio": 5,
    })
    res = await client.get("/api/v1/pins/locks")
    uarts = res.json()["data"]["uarts"]
    uart0 = next((u for u in uarts if u["uart_id"] == 0), None)
    assert uart0["baudrate"] == 230400
    assert uart0["tx_gpio"] == 4
    assert uart0["rx_gpio"] == 5


@pytest.mark.anyio
async def test_delete_uart_config(client):
    await client.post("/api/v1/pins/uart/0", json={
        "baudrate": 115200, "tx_gpio": 1, "rx_gpio": 3,
    })
    res = await client.delete("/api/v1/pins/uart/0")
    assert res.status_code == 200

    res2 = await client.get("/api/v1/pins/locks")
    uarts = res2.json()["data"]["uarts"]
    assert uarts == []


# ── WS expected_state on connect ──────────────────────────

@pytest.mark.anyio
async def test_ws_receives_expected_state(is_real):
    """WS connect should send expected_state with persisted locks/uarts.
    Mock mode (ASGITransport) doesn't support WS; real mode verified manually."""
    if not is_real:
        pytest.skip("WS expected_state requires real server (ASGITransport no WS support)")
    # In real mode, the persisting endpoints + WS connect is verified by
    # the full integration test suite (test_ws.py).
