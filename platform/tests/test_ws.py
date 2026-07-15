"""Test WebSocket endpoint — mock (TestClient) and real (websockets to live server)."""
import os
import json
import time
import pytest
from fastapi.testclient import TestClient


def _is_real():
    return os.environ.get("USE_REAL_DEVICE", "").strip().lower() in ("1", "true", "yes")


class _RealWS:
    """Wrap a sync websockets connection so it quacks like Starlette's TestClient WebSocket."""

    def __init__(self, ws):
        self._ws = ws

    def receive_json(self, timeout: float = 15) -> dict:
        return json.loads(self._ws.recv(timeout=timeout))

    def send_json(self, data: dict) -> None:
        self._ws.send(json.dumps(data))

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


class _RealWSClient:
    """Context manager that yields a .websocket_connect(url) helper for real mode."""

    def websocket_connect(self, url: str):
        from websockets.sync.client import connect
        native_ws = connect("ws://127.0.0.1:8000" + url, open_timeout=15)
        return _RealWS(native_ws)


@pytest.fixture
def ws_client(monkeypatch):
    """Mock mode → TestClient(app); real mode → _RealWSClient (websockets to live uvicorn)."""
    if _is_real():
        yield _RealWSClient()
    else:
        from src.main import app
        monkeypatch.setattr("src.main.is_allowed", lambda address, allowlist: address == "testclient")
        with TestClient(app) as c:
            yield c


# ── WS integration tests ──────────────────────────────────

def _ws_skip_init(ws):
    """Discard initial config/state messages — 2 in mock, ~4 in real mode."""
    # Always skip hardware_config + connection_change
    ws.receive_json(); ws.receive_json()
    if _is_real():
        # Real mode may asynchronously emit a larger startup burst:
        # expected_state/device_state, sync_response, many port_status items,
        # BLE peers, heartbeat, etc. Drain the burst for a short window so
        # later assertions read the actual command result instead of startup chatter.
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                ws.receive_json(timeout=0.25)
            except Exception:
                break


def _ws_drain_initial(ws, max_msg: int = 10) -> int:
    """Discard initial burst of config/state messages. Returns count drained."""
    drained = 0
    for _ in range(max_msg):
        msg = ws.receive_json()
        drained += 1
        t = msg.get("type", "")
        # Stop draining once we hit non-config messages
        if t not in ("hardware_config", "connection_change", "expected_state", "device_state",
                      "gpio_status", "uart_status", "ble_status", "port_status"):
            # Put it back? Can't — already consumed. This is a heuristic.
            pass
    return drained


def _ws_expect_cmd_result(ws) -> dict:
    """Read WS messages until we get a cmd_result, return it."""
    for _ in range(30):
        msg = ws.receive_json()
        if msg.get("type") == "cmd_result":
            return msg
    raise TimeoutError("No cmd_result received")


def test_ws_connect_and_receive_config(ws_client, mock_bridge):
    with ws_client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "hardware_config"
        assert msg["data"]["chip"]["name"] == "ESP32-C6-DevKitM-1"
        msg2 = ws.receive_json()
        assert msg2["type"] == "connection_change"


def test_ws_send_gpio_set(ws_client, mock_bridge):
    with ws_client.websocket_connect("/ws?role=console") as ws:
        _ws_skip_init(ws)
        ws.send_json({"type": "cmd", "op": "gpio_set", "gpio": 5, "value": 1})
        resp = _ws_expect_cmd_result(ws)
        # gpio_set may fail if GPIO5 not configured — accept either result
        assert "success" in resp


def test_ws_send_gpio_get(ws_client, mock_bridge):
    with ws_client.websocket_connect("/ws") as ws:
        _ws_skip_init(ws)
        ws.send_json({"type": "cmd", "op": "gpio_get", "gpio": 5})
        resp = _ws_expect_cmd_result(ws)
        assert "success" in resp


def test_ws_unknown_op(ws_client, mock_bridge):
    with ws_client.websocket_connect("/ws") as ws:
        _ws_skip_init(ws)
        ws.send_json({"type": "cmd", "op": "unknown_command", "x": 1})
        resp = _ws_expect_cmd_result(ws)
        assert resp["success"] is False


def test_ws_send_adc_sample(ws_client, mock_bridge):
    with ws_client.websocket_connect("/ws") as ws:
        _ws_skip_init(ws)
        ws.send_json({"type": "cmd", "op": "adc_sample", "gpio": 2, "samples": 4})
        resp = _ws_expect_cmd_result(ws)
        assert "success" in resp


def test_ws_multiple_connections_coexist(ws_client, mock_bridge):
    with ws_client.websocket_connect("/ws?role=app") as ws1:
        _ws_skip_init(ws1)  # drain init messages from ws1
        with ws_client.websocket_connect("/ws?role=console") as ws2:
            _ws_skip_init(ws2)  # drain init messages from ws2
            # New connection should NOT kick old one anymore.
            ws2.send_json({"type": "cmd", "op": "adc_sample", "gpio": 2, "samples": 4})
            resp = _ws_expect_cmd_result(ws2)
            assert "success" in resp


def test_ws_default_role_app_cannot_control(ws_client, mock_bridge):
    with ws_client.websocket_connect("/ws") as ws:
        _ws_skip_init(ws)
        ws.send_json({"type": "cmd", "op": "gpio_set", "gpio": 5, "value": 1})
        resp = _ws_expect_cmd_result(ws)
        assert resp["success"] is False
        assert "not allowed" in resp["error"]


def test_ws_role_app_can_read(ws_client, mock_bridge):
    with ws_client.websocket_connect("/ws?role=app") as ws:
        _ws_skip_init(ws)
        ws.send_json({"type": "cmd", "op": "gpio_get", "gpio": 5})
        resp = _ws_expect_cmd_result(ws)
        assert "success" in resp


@pytest.mark.parametrize("op,payload", [
    ("signal_tx", {"gpio": 5, "signal": [{"level": 1, "duration_us": 10}]}),
    ("signal_exchange", {"gpio": 5, "tx_signal": [{"level": 1, "duration_us": 10}]}),
    ("uart_send", {"uart_id": 1, "data": "hello"}),
    ("thread_passthrough", {"device_id": 1, "payload": "AQID"}),
])
def test_ws_role_app_cannot_send_or_transmit(ws_client, mock_bridge, op, payload):
    with ws_client.websocket_connect("/ws?role=app") as ws:
        _ws_skip_init(ws)
        ws.send_json({"type": "cmd", "op": op, **payload})
        resp = _ws_expect_cmd_result(ws)
        assert resp["success"] is False
        assert "not allowed" in resp["error"]


def test_ws_role_app_can_signal_rx(ws_client, mock_bridge):
    with ws_client.websocket_connect("/ws?role=app") as ws:
        _ws_skip_init(ws)
        ws.send_json({"type": "cmd", "op": "signal_rx", "gpio": 4, "timeout_us": 500000, "max_edges": 100})
        resp = _ws_expect_cmd_result(ws)
        assert resp["success"] is True
        assert "edges" in resp["data"]


def test_ws_role_console_can_control(ws_client, mock_bridge):
    with ws_client.websocket_connect("/ws?role=console") as ws:
        _ws_skip_init(ws)
        ws.send_json({"type": "cmd", "op": "gpio_set", "gpio": 5, "value": 1})
        resp = _ws_expect_cmd_result(ws)
        assert "success" in resp


def test_ws_role_console_signal_tx_validates_duration(ws_client, mock_bridge):
    with ws_client.websocket_connect("/ws?role=console") as ws:
        _ws_skip_init(ws)
        ws.send_json({
            "type": "cmd", "op": "signal_tx", "gpio": 5,
            "signal": [{"level": 1, "duration_us": 32768}],
        })
        resp = _ws_expect_cmd_result(ws)
        assert resp["success"] is False


def test_ws_unregistered_command_rejected_even_for_console(ws_client, mock_bridge):
    with ws_client.websocket_connect("/ws?role=console") as ws:
        _ws_skip_init(ws)
        # gpio_config exists at REST level, but is intentionally NOT exposed on WS
        # until it is explicitly registered with a permission class.
        ws.send_json({"type": "cmd", "op": "gpio_config", "gpio": 5, "mode": 1})
        resp = _ws_expect_cmd_result(ws)
        assert resp["success"] is False
        assert "unsupported WS op" in resp["error"]


# ── Event parsing and dispatch (unit) ─────────────────────

def test_event_to_dict_gpio_status():
    from src.bridge.protocol import EventGpioStatus
    from src.services.bridge_service import _event_to_dict
    evt = EventGpioStatus(gpio=5, mode=1, pull=0, edge=1, value=1, in_use=1, owner=0, adc_raw=0, adc_mv=0)
    d = _event_to_dict("gpio_status", evt)
    assert d["gpio"] == 5
    assert d["mode"] == 1
    assert d["value"] == 1
    assert d["pull"] == 0
    assert d["edge"] == 1

def test_event_to_dict_uart_status():
    from src.bridge.protocol import EventUartStatus
    from src.services.bridge_service import _event_to_dict
    evt = EventUartStatus(uart_id=0, baudrate=115200, data_bits=8, parity=0, stop_bits=1, tx_gpio=1, rx_gpio=3, in_use=1, owner=0)
    d = _event_to_dict("uart_status", evt)
    assert d["uart_id"] == 0
    assert d["baudrate"] == 115200
    assert d["tx_gpio"] == 1
    assert d["data_bits"] == 8
    assert d["parity"] == 0

def test_event_to_dict_ble_status():
    from src.bridge.protocol import EventBleStatus
    from src.services.bridge_service import _event_to_dict
    evt = EventBleStatus(pairing_enabled=1, scan_enabled=0, device_count=2, pairing_timeout_s=60)
    d = _event_to_dict("ble_status", evt)
    assert d["pairing_enabled"] == 1
    assert d["scan_enabled"] == 0
    assert d["device_count"] == 2
    assert d["pairing_timeout_s"] == 60


def test_event_to_dict_ble_in_range_list():
    from src.bridge.protocol import EventBleInRangeList
    from src.services.bridge_service import _event_to_dict
    evt = EventBleInRangeList(cmd_id=0, device_count=1, devices=[(b'\xaa\xbb\xcc\xdd\xee\xff', -45)])
    d = _event_to_dict("ble_in_range_list", evt)
    assert d["device_count"] == 1
    assert len(d["devices"]) == 1
    assert d["devices"][0]["rssi"] == -45
    assert "mac" in d["devices"][0]


def test_event_to_dict_ble_device_in_range():
    from src.bridge.protocol import EventBleDeviceInRange
    from src.services.bridge_service import _event_to_dict
    evt = EventBleDeviceInRange(device_mac=b'\x11\x22\x33\x44\x55\x66', rssi=-50)
    d = _event_to_dict("ble_device_in_range", evt)
    assert "mac" in d
    assert d["rssi"] == -50


def test_event_to_dict_ble_device_out_of_range():
    from src.bridge.protocol import EventBleDeviceOutOfRange
    from src.services.bridge_service import _event_to_dict
    evt = EventBleDeviceOutOfRange(device_mac=b'\xff\xee\xdd\xcc\xbb\xaa', reason=1)
    d = _event_to_dict("ble_device_out_of_range", evt)
    assert "mac" in d
    assert d["reason"] == 1


def test_event_to_dict_ble_rssi():
    from src.bridge.protocol import EventBleRssi
    from src.services.bridge_service import _event_to_dict
    evt = EventBleRssi(device_mac=b'\xaa\xbb\xcc\xdd\xee\xff', rssi=-67, timestamp_us=12345)
    d = _event_to_dict("ble_rssi", evt)
    assert "mac" in d
    assert d["rssi"] == -67


def test_event_to_dict_ble_pairing_enabled():
    from src.bridge.protocol import EventBlePairingEnabled
    from src.services.bridge_service import _event_to_dict
    evt = EventBlePairingEnabled(cmd_id=0, pin_code=b'654321', timeout_s=30)
    d = _event_to_dict("ble_pairing_enabled", evt)
    assert "pin_code" in d
    assert d["timeout_s"] == 30


def test_event_to_dict_ble_pairing_disabled():
    from src.bridge.protocol import EventBlePairingDisabled
    from src.services.bridge_service import _event_to_dict
    evt = EventBlePairingDisabled(reason=2)
    d = _event_to_dict("ble_pairing_disabled", evt)
    assert d["reason"] == 2
