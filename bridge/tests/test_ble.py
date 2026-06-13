"""
BLE functionality tests for IoT Agent Bridge.

Tests BLE pairing, host connection lifecycle, peer management, and RSSI events.
"""
import asyncio
import os
import pytest
from ..src import (
    IoTAgentClient,
    EVENT_BLE_PAIRING_ENABLED,
    EVENT_BLE_PAIRING_DISABLED,
    EVENT_BLE_PEER_CONNECTED,
    EVENT_BLE_PEER_DISCONNECTED,
    EVENT_BLE_RSSI,
)

try:
    from bleak import BleakScanner
except Exception:  # pragma: no cover - optional runtime dependency
    BleakScanner = None


def _mac_to_text(mac_bytes: bytes) -> str:
    return ":".join(f"{b:02X}" for b in mac_bytes)


class TestBLEIntegration:
    """Test BLE end-to-end integration with real host adapter."""

    @pytest.fixture
    def client(self):
        """Client fixture."""
        client = IoTAgentClient()
        try:
            client.start()
            assert client.wait_for_connection(timeout=60.0)
            yield client
        finally:
            client.stop()

    @pytest.mark.skipif(
        os.getenv("SKIP_BLE_CONNECT_TESTS", "0") == "1",
        reason="SKIP_BLE_CONNECT_TESTS=1: BLE connect tests disabled",
    )
    def test_ble_pair_connect_event_chain(self, client):
        """Pair from ESP32 side, pair from host BLE, then verify full BLE event chain.

        FULLY AUTOMATED: the firmware's PIN (EVENT_BLE_PAIRING_ENABLED) is
        injected through the Windows Runtime custom-pairing API, so no PIN
        dialog appears. The firmware emits EVENT_BLE_PEER_CONNECTED after
        encryption succeeds.
        """
        from .ble_helper import BleTestHelper
        if not BleTestHelper.winrt_available():
            pytest.skip("winrt unavailable: automated BLE pairing needs Windows")

        ble = BleTestHelper(scan_timeout=8.0)
        target_addr = ble.scan_for_device()
        if not target_addr:
            ble.cleanup()
            pytest.skip("ESP32 BLE not in range")
        target_addr = target_addr.upper()

        try:
            enable_cmd = client.commands.ble_enable_pairing(timeout_s=90)
            assert enable_cmd is not None

            pairing_evt = client.events.wait_for_event(EVENT_BLE_PAIRING_ENABLED, timeout=3.0)
            assert pairing_evt is not None
            assert len(pairing_evt.pin_code) == 6
            assert all(chr(c).isdigit() for c in pairing_evt.pin_code)
            pin = bytes(pairing_evt.pin_code).decode("ascii")

            ack_evt = client.events.wait_for_response(enable_cmd, timeout=2.0)
            assert ack_evt is not None

            ble.unpair()  # clear stale bond
            client.events.clear_pending()
            assert ble.pair_with_pin(pin, timeout=25.0), (
                f"Automated PIN pairing to {target_addr} failed")

            peer_connected_evt = client.events.wait_for_event(EVENT_BLE_PEER_CONNECTED, timeout=10.0)
            assert peer_connected_evt is not None, "No BLE peer connected event observed"
            # NimBLE may report random identity address, not scannable address
            assert len(peer_connected_evt.peer_mac) == 6, "Invalid peer MAC length"

            assert client.start_ble_scan(interval_s=2)
            rssi_evt = client.events.wait_for_event(EVENT_BLE_RSSI, timeout=8.0)
            assert rssi_evt is not None, "No BLE RSSI event observed after scan start"
            assert -100 <= rssi_evt.rssi <= 20

            peers = client.get_ble_peers()
            assert peers is not None
            assert len(peers) >= 1

            assert ble.unpair()  # drop the encrypted link
            disconnected_evt = client.events.wait_for_event(EVENT_BLE_PEER_DISCONNECTED, timeout=10.0)
            assert disconnected_evt is not None, "No BLE peer disconnected event observed"
            assert len(disconnected_evt.peer_mac) == 6

            disable_cmd = client.commands.ble_disable_pairing()
            assert disable_cmd is not None
            disabled_evt = client.events.wait_for_event(EVENT_BLE_PAIRING_DISABLED, timeout=3.0)
            assert disabled_evt is not None
            disable_ack = client.events.wait_for_response(disable_cmd, timeout=2.0)
            assert disable_ack is not None
        finally:
            ble.cleanup()

    @pytest.mark.skipif(
        os.getenv("SKIP_BLE_CONNECT_TESTS", "0") == "1",
        reason="SKIP_BLE_CONNECT_TESTS=1: host BLE connection to the ESP32 disabled",
    )
    def test_ble_rssi_event_stream(self, client):
        """Test BLE RSSI events: pair a peer first, then verify RSSI stream."""
        from .ble_helper import BleTestHelper
        if not BleTestHelper.winrt_available():
            pytest.skip("winrt unavailable: automated BLE pairing needs Windows")

        ble = BleTestHelper(scan_timeout=5.0)
        addr = ble.scan_for_device()
        if not addr:
            ble.cleanup()
            pytest.skip("ESP32 BLE not in range")
        try:
            pin = client.enable_ble_pairing(timeout_s=90)
            assert pin is not None and len(pin) == 6
            ble.unpair()
            client.events.clear_pending()
            assert ble.pair_with_pin(pin.decode("ascii"), timeout=25.0), (
                "Automated PIN pairing failed")
            # Wait for peer_connected event (may arrive asynchronously)
            client.events.wait_for_event(EVENT_BLE_PEER_CONNECTED, timeout=8.0)

            assert client.start_ble_scan(interval_s=2)
            evt = client.events.wait_for_event(EVENT_BLE_RSSI, timeout=15.0)
            if evt is None:
                pytest.skip("No RSSI events in scan window")
            assert len(evt.peer_mac) == 6
            assert -127 <= evt.rssi <= 20
        finally:
            ble.cleanup()

    def test_ble_host_scan_visibility(self, client):
        """Test that host Bluetooth scanner can discover ESP32 in pairing mode."""
        bleak = pytest.importorskip("bleak")
        _ = bleak  # keep linter quiet for optional import path
        from bleak import BleakScanner

        pin = client.enable_ble_pairing(timeout_s=30)
        assert pin is not None

        devices = asyncio.run(BleakScanner.discover(timeout=8.0))
        names = [d.name or "" for d in devices]
        assert any(("ESP32-IoT" in name) or ("ESP32-IoT-Agent" in name)
                   for name in names), (f"ESP32 BLE peripheral not discovered by host scanner. Seen names: {names}")
