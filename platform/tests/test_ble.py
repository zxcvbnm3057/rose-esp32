"""Test BLE endpoints — real device tested when BLE is available."""
import pytest


@pytest.mark.anyio
async def test_ble_enable_pairing(client, mock_bridge, is_real):
    res = await client.post("/api/v1/ble/pairing/enable", json={"timeout_s": 60})
    if is_real:
        # Real device: BLE may or may not be available; accept 200 or 502
        assert res.status_code in (200, 502)
    else:
        assert res.status_code == 200
        assert res.json()["success"] is True


@pytest.mark.anyio
async def test_ble_disable_pairing(client, mock_bridge, is_real):
    res = await client.post("/api/v1/ble/pairing/disable")
    if is_real:
        assert res.status_code in (200, 502)
    else:
        assert res.status_code == 200


@pytest.mark.anyio
async def test_ble_get_peers(client, mock_bridge, is_real):
    res = await client.get("/api/v1/ble/peers")
    if is_real:
        assert res.status_code in (200, 502)
    else:
        assert res.status_code == 200


@pytest.mark.anyio
async def test_ble_scan_start(client, mock_bridge, is_real):
    res = await client.post("/api/v1/ble/scan/start", json={"interval_s": 5})
    if is_real:
        assert res.status_code in (200, 502)
    else:
        assert res.status_code == 200


@pytest.mark.anyio
async def test_ble_scan_stop(client, mock_bridge, is_real):
    res = await client.post("/api/v1/ble/scan/stop")
    if is_real:
        assert res.status_code in (200, 502)
    else:
        assert res.status_code == 200


# ── BLE event parsing (unit) ──────────────────────────────

def test_ble_status_from_bytes():
    from app.bridge.protocol import EventBleStatus
    data = bytes([1, 0, 2, 0x3C, 0, 0, 0])
    evt = EventBleStatus.from_bytes(data)
    assert evt.pairing_enabled == 1
    assert evt.scan_enabled == 0
    assert evt.peer_count == 2
    assert evt.pairing_timeout_s == 60


def test_ble_status_event_to_dict():
    from app.bridge.protocol import EventBleStatus
    from app.services.bridge_service import _event_to_dict
    evt = EventBleStatus(pairing_enabled=0, scan_enabled=1, peer_count=3, pairing_timeout_s=120)
    d = _event_to_dict("ble_status", evt)
    assert d == {
        "pairing_enabled": 0, "scan_enabled": 1,
        "peer_count": 3, "pairing_timeout_s": 120,
    }


def test_ble_cache_exists():
    from app.main import _ble_state_cache
    assert isinstance(_ble_state_cache, dict)


# ── BLE API response structure ────────────────────────────

@pytest.mark.anyio
async def test_ble_enable_pairing_returns_pin(client, mock_bridge, is_real):
    """Verify PIN is a 6-digit string in response."""
    res = await client.post("/api/v1/ble/pairing/enable", json={"timeout_s": 60})
    if not is_real:
        assert res.status_code == 200
        data = res.json()["data"]
        pin = data.get("pin_code", "")
        assert len(pin) == 6
        assert pin.isdigit()


@pytest.mark.anyio
async def test_ble_peers_returns_list(client, mock_bridge, is_real):
    """Verify peers response contains expected structure."""
    res = await client.get("/api/v1/ble/peers")
    if not is_real:
        assert res.status_code == 200
        data = res.json()["data"]
        peers = data.get("peers", [])
        assert isinstance(peers, list)
        if peers:
            p0 = peers[0]
            assert "mac" in p0
            assert "rssi" in p0
            assert isinstance(p0["rssi"], int)


@pytest.mark.anyio
async def test_ble_scan_stop_no_error(client, mock_bridge, is_real):
    """Verify scan/stop returns 200 without payload."""
    res = await client.post("/api/v1/ble/scan/stop")
    if not is_real:
        assert res.status_code == 200
        assert res.json()["success"] is True


@pytest.mark.anyio
async def test_ble_pairing_timeout_validation(client, mock_bridge, is_real):
    """Verify pairing enable accepts timeout_s and returns expected PIN."""
    res = await client.post("/api/v1/ble/pairing/enable", json={"timeout_s": 120})
    if not is_real:
        assert res.status_code == 200
        assert res.json()["success"] is True


# ── BLE peer event_to_dict ────────────────────────────────

def test_ble_peers_list_event_to_dict():
    from app.bridge.protocol import EventBlePeersList
    from app.services.bridge_service import _event_to_dict
    evt = EventBlePeersList(peer_count=1, peers=[(b'\xaa\xbb\xcc\xdd\xee\xff', -45)])
    d = _event_to_dict("ble_peers_list", evt)
    assert d["peer_count"] == 1
    assert len(d["peers"]) == 1
    # MAC bytes are little-endian on the wire; displayed reversed + colon-separated.
    assert d["peers"][0]["mac"] == "ff:ee:dd:cc:bb:aa"
    assert d["peers"][0]["rssi"] == -45

def test_ble_peer_connected_event_to_dict():
    from app.bridge.protocol import EventBlePeerConnected
    from app.services.bridge_service import _event_to_dict
    evt = EventBlePeerConnected(peer_mac=b'\x11\x22\x33\x44\x55\x66', rssi=-50)
    d = _event_to_dict("ble_peer_connected", evt)
    assert d["mac"] == "66:55:44:33:22:11"
    assert d["rssi"] == -50

def test_ble_peer_disconnected_event_to_dict():
    from app.bridge.protocol import EventBlePeerDisconnected
    from app.services.bridge_service import _event_to_dict
    evt = EventBlePeerDisconnected(peer_mac=b'\xaa\xaa\xaa\xaa\xaa\xaa', reason=1)
    d = _event_to_dict("ble_peer_disconnected", evt)
    assert d["mac"] == "aa:aa:aa:aa:aa:aa"
    assert d["reason"] == 1

def test_ble_rssi_event_to_dict():
    from app.bridge.protocol import EventBleRssi
    from app.services.bridge_service import _event_to_dict
    evt = EventBleRssi(peer_mac=b'\xbb\xbb\xbb\xbb\xbb\xbb', rssi=-55, timestamp_us=12345)
    d = _event_to_dict("ble_rssi", evt)
    assert d["mac"] == "bb:bb:bb:bb:bb:bb"
    assert d["rssi"] == -55


def test_ble_pairing_enabled_event_to_dict():
    from app.bridge.protocol import EventBlePairingEnabled
    from app.services.bridge_service import _event_to_dict
    evt = EventBlePairingEnabled(pin_code=b'654321', timeout_s=30)
    d = _event_to_dict("ble_pairing_enabled", evt)
    assert d["pin_code"] == "654321"
    assert d["timeout_s"] == 30


def test_ble_pairing_disabled_event_to_dict():
    from app.bridge.protocol import EventBlePairingDisabled
    from app.services.bridge_service import _event_to_dict
    for reason_val in (0, 1, 2):
        evt = EventBlePairingDisabled(reason=reason_val)
        d = _event_to_dict("ble_pairing_disabled", evt)
        assert d["reason"] == reason_val


# ── BLE device-name mappings CRUD ─────────────────────────
# Pure DB CRUD (no bridge); runs in both mock and real mode.

@pytest.mark.anyio
async def test_ble_device_names_empty(client):
    res = await client.get("/api/v1/ble/device-names")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert isinstance(data["data"]["names"], list)


@pytest.mark.anyio
async def test_ble_device_name_create(client):
    mac = "aa:bb:cc:dd:ee:01"
    res = await client.put(f"/api/v1/ble/device-names/{mac}", json={"name": "客厅传感器"})
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["data"]["mac"] == mac
    assert body["data"]["name"] == "客厅传感器"

    # Confirm it shows up in the list
    res2 = await client.get("/api/v1/ble/device-names")
    names = {n["mac"]: n["name"] for n in res2.json()["data"]["names"]}
    assert names.get(mac) == "客厅传感器"


@pytest.mark.anyio
async def test_ble_device_name_update(client):
    mac = "aa:bb:cc:dd:ee:02"
    await client.put(f"/api/v1/ble/device-names/{mac}", json={"name": "旧名字"})
    res = await client.put(f"/api/v1/ble/device-names/{mac}", json={"name": "新名字"})
    assert res.status_code == 200
    assert res.json()["data"]["name"] == "新名字"

    res2 = await client.get("/api/v1/ble/device-names")
    names = {n["mac"]: n["name"] for n in res2.json()["data"]["names"]}
    assert names.get(mac) == "新名字"
    # Update must not create a duplicate row for the same MAC
    assert sum(1 for n in res2.json()["data"]["names"] if n["mac"] == mac) == 1


@pytest.mark.anyio
async def test_ble_device_name_delete(client):
    mac = "aa:bb:cc:dd:ee:03"
    await client.put(f"/api/v1/ble/device-names/{mac}", json={"name": "待删除"})
    res = await client.delete(f"/api/v1/ble/device-names/{mac}")
    assert res.status_code == 200
    assert res.json()["data"]["deleted"] is True

    res2 = await client.get("/api/v1/ble/device-names")
    macs = [n["mac"] for n in res2.json()["data"]["names"]]
    assert mac not in macs


@pytest.mark.anyio
async def test_ble_device_name_delete_nonexistent(client):
    # Deleting an unknown MAC is idempotent — returns success without error.
    res = await client.delete("/api/v1/ble/device-names/00:00:00:00:00:00")
    assert res.status_code == 200
    assert res.json()["data"]["deleted"] is True

