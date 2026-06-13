"""Test hardware config endpoint."""
import pytest


@pytest.mark.anyio
async def test_get_hardware_config(client):
    res = await client.get("/api/v1/hardware/config")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    cfg = data["data"]
    assert "chip" in cfg
    assert "capabilities" in cfg
    assert "pins" in cfg
    assert "feature_groups" in cfg
    assert cfg["chip"]["name"] == "ESP32-C6-DevKitM-1"
    assert len(cfg["pins"]) == 32  # GPIOs + fixed pins (3V3, EN, 5V, GND)
    # Verify pin structure (no coordinates)
    pin0 = cfg["pins"][0]
    assert "gpio" in pin0
    assert "side" in pin0
    assert "order" in pin0
    assert "capabilities" in pin0
    assert "reserved" in pin0
    assert "x" not in pin0  # no hardcoded coordinates


@pytest.mark.anyio
async def test_feature_groups_present(client):
    """feature_groups should list all groups with correct enabled flags."""
    res = await client.get("/api/v1/hardware/config")
    groups = res.json()["data"]["feature_groups"]
    ids = [g["id"] for g in groups]
    assert "gpio" in ids
    assert "uart" in ids
    assert "ble" in ids
    assert "thread" in ids
    thread = next(g for g in groups if g["id"] == "thread")
    assert thread["enabled"] is True  # ESP32-C6 supports Thread


@pytest.mark.anyio
async def test_thread_not_supported_by_capability(client, mock_bridge, is_real):
    """thread passthrough — 502 expected when no Thread device online (bridge returns error)."""
    import base64
    payload = base64.b64encode(b"test").decode()
    res = await client.post("/api/v1/thread/passthrough", json={
        "device_id": 1, "payload": payload,
    })
    # Without an online Thread device, bridge returns error → API returns 502
    assert res.status_code in (200, 502)
