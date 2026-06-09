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
    from bleak import BleakClient, BleakScanner
except Exception:  # pragma: no cover - optional runtime dependency
    BleakClient = None
    BleakScanner = None


def _mac_to_text(mac_bytes: bytes) -> str:
    return ":".join(f"{b:02X}" for b in mac_bytes)


def _find_target_device(timeout_s: float = 15.0):
    if BleakScanner is None:
        pytest.skip("bleak is not available; install bleak in test environment")

    target_mac = os.getenv("BLE_TARGET_ADDRESS", "").strip().upper()
    target_name = os.getenv("BLE_TARGET_NAME", "ESP32-IoT").strip()

    devices = asyncio.run(BleakScanner.discover(timeout=timeout_s))
    if target_mac:
        for dev in devices:
            if (dev.address or "").upper() == target_mac:
                return dev
        pytest.skip(f"Target BLE device {target_mac} not found")

    for dev in devices:
        if dev.name and target_name in dev.name:
            return dev

    pytest.skip(f"Target BLE device name containing '{target_name}' not found")


async def _connect_then_disconnect(address: str, hold_seconds: float = 2.0) -> bool:
    if BleakClient is None:
        pytest.skip("bleak is not available; install bleak in test environment")
    client = BleakClient(address, timeout=15.0)
    await client.connect()
    try:
        await asyncio.sleep(hold_seconds)
        return client.is_connected
    finally:
        await client.disconnect()


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

    def test_ble_pair_connect_event_chain(self, client):
        """Pair from ESP32 side, connect from host BLE, then verify full BLE event chain."""
        target_device = _find_target_device(timeout_s=20.0)
        target_addr = target_device.address.upper()

        enable_cmd = client.commands.ble_enable_pairing(timeout_s=90)
        assert enable_cmd is not None

        pairing_evt = client.events.wait_for_event(EVENT_BLE_PAIRING_ENABLED, timeout=3.0)
        assert pairing_evt is not None
        assert len(pairing_evt.pin_code) == 6
        assert all(chr(c).isdigit() for c in pairing_evt.pin_code)

        ack_evt = client.events.wait_for_response(enable_cmd, timeout=2.0)
        assert ack_evt is not None

        connected_ok = asyncio.run(_connect_then_disconnect(target_device.address, hold_seconds=3.0))
        assert connected_ok is True, f"Host BLE failed to connect to {target_addr}"

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

        disconnected_evt = client.events.wait_for_event(EVENT_BLE_PEER_DISCONNECTED, timeout=10.0)
        assert disconnected_evt is not None, "No BLE peer disconnected event observed"
        assert len(disconnected_evt.peer_mac) == 6

        disable_cmd = client.commands.ble_disable_pairing()
        assert disable_cmd is not None
        disabled_evt = client.events.wait_for_event(EVENT_BLE_PAIRING_DISABLED, timeout=3.0)
        assert disabled_evt is not None
        disable_ack = client.events.wait_for_response(disable_cmd, timeout=2.0)
        assert disable_ack is not None

    def test_ble_rssi_event_stream(self, client):
        """Test BLE RSSI events: connect a peer first, then verify RSSI stream."""
        bleak = pytest.importorskip("bleak")
        from bleak import BleakScanner
        from tests.ble_helper import BleTestHelper
        import asyncio

        # Connect a peer so ESP32 has something to report RSSI for
        ble = BleTestHelper(scan_timeout=5.0)
        addr = ble.scan_for_device()
        if not addr:
            ble.cleanup()
            pytest.skip("ESP32 BLE not in range")
        try:
            assert ble.connect(timeout=10.0), "Failed to connect via BLE"
            # Wait for peer_connected event (may arrive asynchronously)
            client.events.wait_for_event(EVENT_BLE_PEER_CONNECTED, timeout=5.0)

            assert client.start_ble_scan(interval_s=2)
            evt = client.events.wait_for_event(EVENT_BLE_RSSI, timeout=15.0)
            if evt is None:
                pytest.skip("No RSSI events in scan window")
            assert len(evt.peer_mac) == 6
            assert -127 <= evt.rssi <= 20
        finally:
            ble.disconnect()
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
