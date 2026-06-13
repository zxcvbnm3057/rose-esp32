"""Test system endpoints — works with both mock and real device."""
import base64
import pytest


@pytest.mark.anyio
async def test_device_status(client, mock_bridge):
    res = await client.get("/api/v1/device/status")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert isinstance(data["data"]["connected"], bool)


@pytest.mark.anyio
async def test_ping(client, mock_bridge, is_real):
    res = await client.post("/api/v1/system/ping")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True


@pytest.mark.anyio
async def test_heartbeat(client, mock_bridge):
    res = await client.post("/api/v1/system/heartbeat")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True


@pytest.mark.anyio
async def test_sync(client, mock_bridge, is_real):
    res = await client.post("/api/v1/system/sync")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "session_version" in data["data"]


@pytest.mark.anyio
async def test_sync_confirm(client, mock_bridge, is_real):
    res = await client.post("/api/v1/system/sync/confirm", json={
        "correlation_id": 42, "stage": 0,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True


@pytest.mark.anyio
async def test_thread_not_supported(client, mock_bridge, is_real):
    payload = base64.b64encode(b"test").decode()
    res = await client.post("/api/v1/thread/passthrough", json={
        "device_id": 1, "payload": payload,
    })
    # Without Thread device online: 502 (bridge error) is expected in real mode
    assert res.status_code in (200, 502)
