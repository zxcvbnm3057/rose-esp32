"""Tests for BLE event parsing."""

import struct
import pytest
from ..src.protocol import (
    MessageFrame,
    MSG_TYPE_EVENT,
    EVENT_BLE_PAIRING_ENABLED,
    EVENT_BLE_PAIRING_DISABLED,
    EVENT_BLE_PEER_CONNECTED,
    EVENT_BLE_PEER_DISCONNECTED,
    EVENT_BLE_PEERS_LIST,
    EVENT_BLE_RSSI,
)
from ..src.events import EventHandler


def _make_frame(opcode: int, payload: bytes) -> MessageFrame:
    """Helper: build an event frame with opcode prepended."""
    full_payload = bytes([opcode]) + payload
    frame = MessageFrame(version=1,
                         msg_type=MSG_TYPE_EVENT,
                         length=len(full_payload),
                         cmd_id=0,
                         crc=0,
                         payload=full_payload)
    return frame


def test_parse_ble_status():
    """Test EventHandler can parse events without crashing."""
    handler = EventHandler()
    # Use a simple known event type to verify handler pipeline works
    pin = b'\x01\x02\x03\x04\x05\x06'
    # Layout (packed): cmd_id(H) pin(6) timeout(I)
    payload = struct.pack('<H', 0) + pin + struct.pack('<I', 60)
    frame = _make_frame(EVENT_BLE_PAIRING_ENABLED, payload)
    handler.handle_event(frame)
    # Should not raise; events stored in pending_events
    assert EVENT_BLE_PAIRING_ENABLED in handler.pending_events


def test_parse_ble_peers_list():
    """Test BLE peers list event parsing."""
    handler = EventHandler()
    mac1 = b'\xaa\xbb\xcc\xdd\xee\xff'
    rssi1 = struct.pack('<b', -45)
    mac2 = b'\x11\x22\x33\x44\x55\x66'
    rssi2 = struct.pack('<b', -72)
    # Layout (packed): cmd_id(H) peer_count(B) then peers
    payload = struct.pack('<H', 0) + b'\x02' + mac1 + rssi1 + mac2 + rssi2  # peer_count=2
    frame = _make_frame(EVENT_BLE_PEERS_LIST, payload)
    handler.handle_event(frame)
    assert EVENT_BLE_PEERS_LIST in handler.pending_events


def test_parse_ble_peer_connected():
    """Test BLE peer connected event parsing."""
    handler = EventHandler()
    mac = b'\xaa\xbb\xcc\xdd\xee\xff'
    rssi = struct.pack('<b', -50)
    frame = _make_frame(EVENT_BLE_PEER_CONNECTED, mac + rssi)
    handler.handle_event(frame)
    assert EVENT_BLE_PEER_CONNECTED in handler.pending_events


def test_parse_ble_peer_disconnected():
    """Test BLE peer disconnected event parsing."""
    handler = EventHandler()
    mac = b'\xaa\xbb\xcc\xdd\xee\xff'
    reason = b'\x13'  # BLE_ERR_REM_USER_CONN_TERM
    frame = _make_frame(EVENT_BLE_PEER_DISCONNECTED, mac + reason)
    handler.handle_event(frame)
    assert EVENT_BLE_PEER_DISCONNECTED in handler.pending_events


def test_parse_ble_rssi():
    """Test BLE RSSI event parsing."""
    handler = EventHandler()
    mac = b'\xaa\xbb\xcc\xdd\xee\xff'
    rssi = struct.pack('<b', -60)
    ts = struct.pack('<q', 1234567890)
    frame = _make_frame(EVENT_BLE_RSSI, mac + rssi + ts)
    handler.handle_event(frame)
    assert EVENT_BLE_RSSI in handler.pending_events


def test_parse_ble_pairing_enabled():
    """Test BLE pairing enabled event parsing."""
    handler = EventHandler()
    pin = b'\x01\x02\x03\x04\x05\x06'
    timeout = struct.pack('<I', 60)
    # Layout (packed): cmd_id(H) pin(6) timeout(I)
    frame = _make_frame(EVENT_BLE_PAIRING_ENABLED, struct.pack('<H', 0) + pin + timeout)
    handler.handle_event(frame)
    assert EVENT_BLE_PAIRING_ENABLED in handler.pending_events


def test_parse_ble_pairing_disabled():
    """Test BLE pairing disabled event parsing."""
    handler = EventHandler()
    reason = b'\x00'
    frame = _make_frame(EVENT_BLE_PAIRING_DISABLED, reason)
    handler.handle_event(frame)
    assert EVENT_BLE_PAIRING_DISABLED in handler.pending_events
