"""Unit tests for MessageFrame framing and CRC16 (bridge/protocol.py)."""

import struct
import pytest

from ..src.protocol import (
    MessageFrame,
    MSG_TYPE_CMD,
    MSG_TYPE_ACK,
    MSG_TYPE_EVENT,
    MSG_TYPE_ERROR,
    CMD_GPIO_SET,
)


def _build(payload: bytes, msg_type: int = MSG_TYPE_CMD, cmd_id: int = 1) -> MessageFrame:
    frame = MessageFrame(version=1, msg_type=msg_type, length=len(payload),
                         cmd_id=cmd_id, crc=0, payload=payload)
    frame.crc = frame.calculate_crc()
    return frame


def test_msg_type_values():
    assert MSG_TYPE_CMD == 0x01
    assert MSG_TYPE_ACK == 0x02
    assert MSG_TYPE_EVENT == 0x03
    assert MSG_TYPE_ERROR == 0x04


def test_header_is_8_bytes():
    frame = _build(b'')
    assert len(frame.to_bytes()) == 8


def test_roundtrip_with_payload():
    payload = bytes([CMD_GPIO_SET]) + struct.pack('<BB', 5, 1)
    frame = _build(payload, cmd_id=0x1234)
    restored = MessageFrame.from_bytes(frame.to_bytes())
    assert restored.version == 1
    assert restored.msg_type == MSG_TYPE_CMD
    assert restored.length == len(payload)
    assert restored.cmd_id == 0x1234
    assert restored.payload == payload
    assert restored.crc == frame.crc


def test_from_bytes_truncates_to_length():
    payload = b'\x10\x05\x01'
    frame = _build(payload)
    # append trailing garbage that should be ignored (length-bounded)
    raw = frame.to_bytes() + b'\xff\xff\xff'
    restored = MessageFrame.from_bytes(raw)
    assert restored.payload == payload


def test_from_bytes_rejects_short_buffer():
    with pytest.raises(ValueError):
        MessageFrame.from_bytes(b'\x01\x01\x00')


def test_crc_initial_value_for_empty_payload():
    # CRC16/MODBUS over the 6-byte header with zero fields except version/type.
    frame = MessageFrame(version=1, msg_type=MSG_TYPE_CMD, length=0,
                         cmd_id=0, crc=0, payload=b'')
    expected = frame.calculate_crc()
    assert frame.crc == 0  # not yet assigned
    frame.crc = expected
    # CRC must be reproducible and in u16 range
    assert 0 <= expected <= 0xFFFF
    assert frame.calculate_crc() == expected


def test_crc_changes_with_payload():
    a = _build(b'\x01')
    b = _build(b'\x02')
    assert a.crc != b.crc


def test_crc_changes_with_cmd_id():
    a = _build(b'\x01', cmd_id=1)
    b = _build(b'\x01', cmd_id=2)
    assert a.crc != b.crc


def test_crc_known_vector():
    """CRC16 (init 0xFFFF, poly 0xA001) over a fixed frame is stable."""
    frame = MessageFrame(version=1, msg_type=MSG_TYPE_CMD, length=1,
                         cmd_id=1, crc=0, payload=b'\xff')
    crc = frame.calculate_crc()
    # Recompute manually to guard against accidental algorithm changes.
    data = struct.pack('<BBHH', 1, MSG_TYPE_CMD, 1, 1) + b'\xff'
    ref = 0xFFFF
    for byte in data:
        ref ^= byte
        for _ in range(8):
            ref = (ref >> 1) ^ 0xA001 if ref & 1 else ref >> 1
    assert crc == ref
