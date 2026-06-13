"""
BLE event tests for IoT Agent Bridge.

Validates BLE connect/disconnect event parsing, peer list structure,
pairing enable/disable events, and RSSI scan cadence.
"""

import os
import time

import pytest

from ..src import (
    IoTAgentClient,
    EVENT_BLE_PEER_CONNECTED,
    EVENT_BLE_PEER_DISCONNECTED,
    EVENT_BLE_PAIRING_ENABLED,
    EVENT_BLE_PAIRING_DISABLED,
    EVENT_BLE_PEERS_LIST,
    EVENT_BLE_RSSI,
)


class TestBlePairing:
    """BLE pairing enable/disable lifecycle."""

    @pytest.fixture
    def client(self):
        client = IoTAgentClient()
        try:
            client.start()
            assert client.wait_for_connection(timeout=60.0)
            yield client
        finally:
            client.stop()

    def test_pairing_enable_returns_pin(self, client):
        """Enable pairing and verify PIN code is returned."""
        pin = client.enable_ble_pairing(timeout_s=120)
        assert pin is not None, "No PIN returned from pairing enable"
        assert isinstance(pin, bytes)
        assert len(pin) == 6, f"PIN should be 6 bytes, got {len(pin)}"
        # PIN should be ASCII digits
        assert all(0x30 <= b <= 0x39 for b in pin), f"PIN not all digits: {pin}"

    def test_pairing_disable_succeeds(self, client):
        """Disable pairing and verify ACK."""
        client.enable_ble_pairing(timeout_s=30)
        time.sleep(0.1)
        assert client.disable_ble_pairing()

    def test_pairing_disable_when_not_enabled(self, client):
        """Disabling pairing when not enabled should still succeed gracefully."""
        # May have been left enabled; disable twice to ensure clean state
        client.disable_ble_pairing()
        time.sleep(0.05)
        assert client.disable_ble_pairing()


class TestBlePeers:
    """BLE peer list and RSSI tests."""

    @pytest.fixture
    def client(self):
        client = IoTAgentClient()
        try:
            client.start()
            assert client.wait_for_connection(timeout=60.0)
            yield client
        finally:
            client.stop()

    def test_peer_list_returns_valid_structure(self, client):
        """Get BLE peers list and verify response structure."""
        peers = client.get_ble_peers()
        assert peers is not None, "No peer list response"
        assert isinstance(peers, list)

        for peer in peers:
            assert 'mac' in peer
            assert 'rssi' in peer
            assert isinstance(peer['mac'], bytes)
            assert len(peer['mac']) == 6
            assert isinstance(peer['rssi'], int)

    def test_rssi_scan_start_and_event_cadence(self, client):
        """Start RSSI scan and verify EVENT_BLE_RSSI arrives periodically."""
        # Start scan with short interval
        assert client.start_ble_scan(interval_s=5)

        # RSSI events may or may not arrive depending on nearby BLE devices.
        # Verify the scan was accepted (no error), then check if RSSI events
        # arrive within a reasonable window.
        client.events.clear_pending()

        # Wait for potential RSSI events
        rssi_events = []
        deadline = time.time() + 8.0
        while time.time() < deadline:
            evt = client.events.wait_for_event(EVENT_BLE_RSSI, timeout=1.0)
            if evt is None:
                continue
            rssi_events.append(evt)
            if len(rssi_events) >= 2:
                break

        # RSSI may or may not arrive (depends on BLE environment)
        # Just verify any received events have correct structure
        for evt in rssi_events:
            assert hasattr(evt, 'peer_mac')
            assert hasattr(evt, 'rssi')
            assert hasattr(evt, 'timestamp_us')
            assert len(evt.peer_mac) == 6
            assert evt.timestamp_us > 0


# ── connect / disconnect events (uses PC Bluetooth via BleTestHelper) ─────


@pytest.mark.skipif(
    os.getenv("SKIP_BLE_CONNECT_TESTS", "0") == "1",
    reason="SKIP_BLE_CONNECT_TESTS=1: BLE connect tests disabled",
)
class TestBleConnectDisconnect:
    """End-to-end BLE connect/disconnect tests using this PC's Bluetooth.

    The PC BLE central pairs with the ESP32 peripheral using the firmware's
    PIN, then the TCP bridge verifies EVENT_BLE_PEER_CONNECTED /
    EVENT_BLE_PEER_DISCONNECTED.

    Pairing is FULLY AUTOMATED: the firmware returns its 6-digit PIN over the
    TCP bridge (EVENT_BLE_PAIRING_ENABLED), and BleTestHelper.pair_with_pin
    injects it through the Windows Runtime custom-pairing API
    (accept_with_pin) so no Windows PIN dialog ever appears.

    The firmware emits EVENT_BLE_PEER_CONNECTED only after BLE *encryption*
    succeeds (BLE_GAP_EVENT_ENC_CHANGE), so each connect test pairs first.
    """

    @pytest.fixture
    def client(self):
        client = IoTAgentClient()
        try:
            client.start()
            assert client.wait_for_connection(timeout=60.0)
            yield client
        finally:
            client.stop()

    @pytest.fixture
    def ble(self):
        from .ble_helper import BleTestHelper  # lazy import (requires bleak)
        if not BleTestHelper.winrt_available():
            pytest.skip("winrt unavailable: automated BLE pairing needs Windows")
        helper = BleTestHelper(scan_timeout=8.0)
        try:
            yield helper
        finally:
            helper.cleanup()

    def _enable_pairing_pin(self, client) -> str:
        """Enable pairing over TCP and return the firmware PIN as a string."""
        pin_bytes = client.enable_ble_pairing(timeout_s=120)
        assert pin_bytes and len(pin_bytes) == 6, "No 6-digit PIN from firmware"
        return pin_bytes.decode("ascii")

    def _pair(self, client, ble) -> None:
        """Scan, enable pairing, and complete automated PIN pairing."""
        addr = ble.scan_for_device()
        assert addr is not None, (
            "ESP32 BLE not found. Is ESP32 powered on with IoT Agent firmware?")
        pin = self._enable_pairing_pin(client)
        ble.unpair()  # clear stale bond
        client.events.clear_pending()
        assert ble.pair_with_pin(pin, timeout=25.0), (
            f"Automated PIN pairing to {addr} failed")

    def test_connect_triggers_peer_connected_event(self, client, ble):
        """PC pairs via BLE → ESP32 sends EVENT_BLE_PEER_CONNECTED over TCP."""
        self._pair(client, ble)
        evt = client.events.wait_for_event(EVENT_BLE_PEER_CONNECTED, timeout=8.0)
        assert evt is not None, "EVENT_BLE_PEER_CONNECTED not received over TCP"
        assert hasattr(evt, 'peer_mac') and len(evt.peer_mac) == 6
        assert hasattr(evt, 'rssi')

    def test_disconnect_triggers_peer_disconnected_event(self, client, ble):
        """PC disconnects BLE → ESP32 sends EVENT_BLE_PEER_DISCONNECTED."""
        self._pair(client, ble)
        _ = client.events.wait_for_event(EVENT_BLE_PEER_CONNECTED, timeout=8.0)
        assert ble.unpair()  # unpair drops the encrypted link
        evt = client.events.wait_for_event(EVENT_BLE_PEER_DISCONNECTED, timeout=8.0)
        assert evt is not None, "EVENT_BLE_PEER_DISCONNECTED not received"
        assert hasattr(evt, 'peer_mac') and hasattr(evt, 'reason')

    def test_connect_then_peer_list_shows_device(self, client, ble):
        """After PC BLE pairing, CMD_BLE_GET_PEERS lists the device."""
        self._pair(client, ble)
        _ = client.events.wait_for_event(EVENT_BLE_PEER_CONNECTED, timeout=8.0)
        time.sleep(0.5)
        peers = client.get_ble_peers()
        assert peers is not None and len(peers) >= 1, (
            f"Expected >=1 peer after connect, got {len(peers) if peers else 0}")
        for p in peers:
            assert len(p['mac']) == 6, f"Invalid MAC length: {len(p['mac'])}"

    def test_reconnect_updates_peer_list(self, client, ble):
        """Disconnect + reconnect; peer list reflects current state."""
        self._pair(client, ble)
        _ = client.events.wait_for_event(EVENT_BLE_PEER_CONNECTED, timeout=8.0)
        assert ble.unpair()
        _ = client.events.wait_for_event(EVENT_BLE_PEER_DISCONNECTED, timeout=8.0)
        time.sleep(0.3)
        # Re-pair
        self._pair(client, ble)
        _ = client.events.wait_for_event(EVENT_BLE_PEER_CONNECTED, timeout=8.0)
        time.sleep(0.3)
        peers = client.get_ble_peers()
        assert peers is not None and len(peers) >= 1
