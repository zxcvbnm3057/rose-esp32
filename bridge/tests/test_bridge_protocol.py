"""Tests for IoT Agent protocol message encoding/decoding."""

import struct
import pytest
from ..src.protocol import (
    MessageFrame,
    MSG_TYPE_CMD,
    MSG_TYPE_EVENT,
    CMD_GPIO_CONFIG,
    CMD_GPIO_SET,
    CMD_GPIO_GET,
    CMD_BLE_ENABLE_PAIRING,
    CMD_BLE_START_SCAN,
    CMD_BLE_STOP_SCAN,
    EVENT_BLE_PEER_CONNECTED,
    EVENT_BLE_RSSI,
    CmdGpioConfig,
    CmdGpioSet,
    CmdBleEnablePairing,
    CmdBleStartScan,
    CmdBleStopScan,
    CmdPortBind,
    CmdPortUnbind,
    CmdPortStatus,
    RESOURCE_GPIO,
)


def test_pack_message():
    """Test basic message packing."""
    payload = b'\x01\x02\x03'
    frame = MessageFrame(version=1, msg_type=MSG_TYPE_CMD, length=len(payload), cmd_id=0x42, crc=0, payload=payload)
    frame.crc = frame.calculate_crc()
    data = frame.to_bytes()
    assert len(data) == 8 + len(payload)
    parsed = MessageFrame.from_bytes(data)
    assert parsed.version == 1
    assert parsed.msg_type == MSG_TYPE_CMD
    assert parsed.length == len(payload)
    assert parsed.cmd_id == 0x42
    assert parsed.payload == payload


def test_unpack_message():
    """Test message unpacking with empty payload."""
    frame = MessageFrame(version=1, msg_type=MSG_TYPE_EVENT, length=0, cmd_id=0, crc=0, payload=b'')
    frame.crc = frame.calculate_crc()
    data = frame.to_bytes()
    parsed = MessageFrame.from_bytes(data)
    assert parsed.payload == b''
    assert parsed.length == 0


def test_bind():
    """Test port bind command serialization."""
    cmd = CmdPortBind(resource_type=RESOURCE_GPIO, id=5, owner_id=42)
    data = cmd.to_bytes()
    assert len(data) == 4  # BBH
    assert data[0] == RESOURCE_GPIO
    assert data[1] == 5
    owner = struct.unpack('<H', data[2:4])[0]
    assert owner == 42


def test_start():
    """Test BLE start scan command."""
    cmd = CmdBleStartScan(interval_s=5)
    data = cmd.to_bytes()
    interval = struct.unpack('<I', data)[0]
    assert interval == 5


def test_stop():
    """Test BLE stop scan command."""
    cmd = CmdBleStopScan()
    data = cmd.to_bytes()
    assert data == b''  # No payload for stop scan


def test_command_types():
    """Verify all command opcodes are unique."""
    cmds = {
        CMD_GPIO_CONFIG,
        CMD_GPIO_SET,
        CMD_GPIO_GET,
        CMD_BLE_ENABLE_PAIRING,
        CMD_BLE_START_SCAN,
        CMD_BLE_STOP_SCAN,
    }
    assert len(cmds) == 6


def test_event_types():
    """Verify event opcodes are within valid range."""
    events = {EVENT_BLE_PEER_CONNECTED, EVENT_BLE_RSSI}
    for e in events:
        assert 0 <= e <= 0xFF


def test_ble_stop_scan():
    """Test CMD_BLE_STOP_SCAN opcode value."""
    assert CMD_BLE_STOP_SCAN == 0x54
    cmd = CmdBleStopScan()
    assert cmd.to_bytes() == b''
