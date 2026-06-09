"""Test port/bind endpoints — unbind first in real mode."""
import pytest


@pytest.mark.anyio
async def test_port_bind(client, mock_bridge, is_real):
    # Ensure clean state: unbind first
    await client.post("/api/v1/port/unbind", json={"resource_type": 0, "id": 5})
    res = await client.post("/api/v1/port/bind", json={
        "resource_type": 0, "id": 5, "owner_id": 1,
    })
    assert res.status_code == 200
    assert res.json()["success"] is True


@pytest.mark.anyio
async def test_port_unbind(client, mock_bridge, is_real):
    # Bind first to ensure something to unbind
    await client.post("/api/v1/port/unbind", json={"resource_type": 0, "id": 5})
    await client.post("/api/v1/port/bind", json={"resource_type": 0, "id": 5, "owner_id": 1})
    res = await client.post("/api/v1/port/unbind", json={
        "resource_type": 0, "id": 5,
    })
    assert res.status_code == 200
    assert res.json()["success"] is True


@pytest.mark.anyio
async def test_port_status(client, mock_bridge, is_real):
    res = await client.get("/api/v1/port/status?resource_type=0&id=5")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "in_use" in data["data"]
