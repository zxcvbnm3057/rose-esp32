"""Unit tests for event parsing (bridge/protocol.py + bridge/events.py).

Covers every event structure's `from_bytes` against the exact byte layout
emitted by the firmware, plus the EventHandler dispatch pipeline.
"""

import struct
import pytest

from ..src.protocol import (
    MessageFrame,
    MSG_TYPE_EVENT,
    EVENT_CMD_ACK,
    EVENT_GPIO_VALUE,
    EVENT_GPIO_EDGE,
    EVENT_ADC_VALUE,
    EVENT_GPIO_SIGNAL_CAPTURED,
    EVENT_UART_RX,
    EVENT_THREAD_RESPONSE,
    EVENT_SYNC_RESPONSE,
    EVENT_PORT_STATUS,
    EVENT_HEARTBEAT,
    EVENT_ERROR,
    EVENT_GPIO_STATUS,
    EVENT_UART_STATUS,
    EVENT_BLE_STATUS,
    EventCmdAck,
    EventGpioValue,
    EventGpioEdge,
    EventAdcValue,
    EventGpioSignalCaptured,
    EventUartRx,
    EventThreadResponse,
    EventSyncResponse,
    EventPortStatus,
    EventHeartbeat,
    EventError,
    EventGpioStatus,
    EventUartStatus,
    EventBleStatus,
)
from ..src.events import EventHandler


def _frame(opcode: int, payload: bytes) -> MessageFrame:
    full = bytes([opcode]) + payload
    return MessageFrame(version=1, msg_type=MSG_TYPE_EVENT, length=len(full),
                        cmd_id=0, crc=0, payload=full)


# ── Event opcode value contract ─────────────────────────────────────────

def test_event_opcode_values():
    assert EVENT_CMD_ACK == 0x20
    assert EVENT_GPIO_VALUE == 0x21
    assert EVENT_GPIO_EDGE == 0x22
    assert EVENT_ADC_VALUE == 0x23
    assert EVENT_GPIO_SIGNAL_CAPTURED == 0x24
    assert EVENT_UART_RX == 0x30
    assert EVENT_UART_STATUS == 0x31
    assert EVENT_THREAD_RESPONSE == 0x40
    assert EVENT_PORT_STATUS == 0x50
    assert EVENT_GPIO_STATUS == 0x51
    assert EVENT_SYNC_RESPONSE == 0x66
    assert EVENT_BLE_STATUS == 0x67
    assert EVENT_HEARTBEAT == 0xFD
    assert EVENT_ERROR == 0xFE


# ── Individual structure parsing ────────────────────────────────────────

def test_cmd_ack_parse():
    data = struct.pack('<HBBI', 0x1234, 0, 0, 0xCAFEBABE)
    ev = EventCmdAck.from_bytes(data)
    assert ev.cmd_id == 0x1234
    assert ev.status == 0
    assert ev.error_code == 0
    assert ev.correlation_id == 0xCAFEBABE


def test_gpio_value_parse():
    # Layout (packed): cmd_id(H) gpio(B) value(B) timestamp(q)
    data = struct.pack('<HBBq', 77, 6, 1, 1_700_000)
    ev = EventGpioValue.from_bytes(data)
    assert ev.cmd_id == 77
    assert ev.gpio == 6
    assert ev.value == 1
    assert ev.timestamp_us == 1_700_000


def test_gpio_value_short_raises():
    with pytest.raises(ValueError):
        EventGpioValue.from_bytes(b'\x06\x01')


def test_gpio_edge_parse():
    data = struct.pack('<BBq', 4, 1, 999)
    ev = EventGpioEdge.from_bytes(data)
    assert ev.gpio == 4
    assert ev.edge_type == 1
    assert ev.timestamp_us == 999


def test_adc_value_packed_layout():
    # Layout (packed): cmd_id(H) gpio(B) value(H) timestamp(q)
    data = struct.pack('<HBHq', 88, 6, 1720, 12345)
    ev = EventAdcValue.from_bytes(data)
    assert ev.cmd_id == 88
    assert ev.gpio == 6
    assert ev.value == 1720
    assert ev.timestamp_us == 12345


def test_signal_captured_parse():
    edges = [(1, 100), (0, 250), (1, 75)]
    # Layout (packed): cmd_id(H) gpio(B) edge_count(H) timestamp(q)
    payload = struct.pack('<HBHq', 33, 5, len(edges), 42)
    for level, dur in edges:
        payload += struct.pack('<BI', level, dur)
    ev = EventGpioSignalCaptured.from_bytes(payload)
    assert ev.cmd_id == 33
    assert ev.gpio == 5
    assert ev.edge_count == 3
    assert ev.timestamp_us == 42
    assert [(e.level, e.duration_us) for e in ev.edges] == edges


def test_signal_captured_empty():
    payload = struct.pack('<HBHq', 33, 5, 0, 0)
    ev = EventGpioSignalCaptured.from_bytes(payload)
    assert ev.edge_count == 0
    assert ev.edges == []


def test_uart_rx_parse():
    body = b'HELLO'
    payload = struct.pack('<BHq', 0, len(body), 7) + body
    ev = EventUartRx.from_bytes(payload)
    assert ev.uart_id == 0
    assert ev.length == 5
    assert ev.data == body


def test_thread_response_parse():
    body = b'\x01\x02'
    payload = struct.pack('<HHIq', 9, len(body), 0xABCD, 88) + body
    ev = EventThreadResponse.from_bytes(payload)
    assert ev.device_id == 9
    assert ev.payload_len == 2
    assert ev.correlation_id == 0xABCD
    assert ev.timestamp_us == 88
    assert ev.payload == body


def test_sync_response_parse():
    # Layout (packed): cmd_id(H) session_version(I) pending_cmd(H) pending_thread(H) port_status(H)
    data = struct.pack('<HIHHH', 55, 3, 1, 2, 4)
    ev = EventSyncResponse.from_bytes(data)
    assert ev.cmd_id == 55
    assert ev.session_version == 3
    assert ev.pending_cmd_count == 1
    assert ev.pending_thread_count == 2
    assert ev.port_status_count == 4


def test_port_status_parse():
    data = struct.pack('<BBBHBB', 0, 5, 1, 42, 1, 1)
    ev = EventPortStatus.from_bytes(data)
    assert ev.resource_type == 0
    assert ev.id == 5
    assert ev.mode == 1
    assert ev.owner == 42
    assert ev.in_use == 1
    assert ev.value == 1


def test_heartbeat_parse():
    data = struct.pack('<IB', 1_700_000_000, 1)
    ev = EventHeartbeat.from_bytes(data)
    assert ev.timestamp == 1_700_000_000
    assert ev.connection_state == 1


def test_error_parse():
    data = struct.pack('<HBB', 0x10, 0, 4) + b'conflict'
    ev = EventError.from_bytes(data)
    assert ev.cmd_id == 0x10
    assert ev.err_code == 4
    assert 'conflict' in ev.message


def test_gpio_status_parse():
    data = struct.pack('<BBBBBBHHH', 6, 3, 0, 0, 0, 1, 42, 1720, 1386)
    ev = EventGpioStatus.from_bytes(data)
    assert ev.gpio == 6
    assert ev.mode == 3
    assert ev.in_use == 1
    assert ev.owner == 42
    assert ev.adc_raw == 1720
    assert ev.adc_mv == 1386


def test_uart_status_parse():
    data = struct.pack('<BIBBBBBBH', 0, 115200, 8, 0, 1, 1, 3, 1, 42)
    ev = EventUartStatus.from_bytes(data)
    assert ev.uart_id == 0
    assert ev.baudrate == 115200
    assert ev.tx_gpio == 1
    assert ev.rx_gpio == 3
    assert ev.in_use == 1
    assert ev.owner == 42


def test_ble_status_parse():
    data = struct.pack('<BBBI', 1, 0, 2, 60)
    ev = EventBleStatus.from_bytes(data)
    assert ev.pairing_enabled == 1
    assert ev.scan_enabled == 0
    assert ev.peer_count == 2
    assert ev.pairing_timeout_s == 60


# ── EventHandler dispatch pipeline ──────────────────────────────────────

def test_handler_parses_and_stores_by_opcode():
    handler = EventHandler()
    payload = struct.pack('<HBBI', 0x1234, 0, 0, 0)
    handler.handle_event(_frame(EVENT_CMD_ACK, payload))
    ev = handler.wait_for_event(EVENT_CMD_ACK, timeout=0.5)
    assert ev is not None
    assert ev.cmd_id == 0x1234


def test_handler_callback_invoked():
    handler = EventHandler()
    seen = []
    handler.register_callback(EVENT_GPIO_VALUE, lambda e: seen.append(e))
    payload = struct.pack('<HBBq', 0, 6, 1, 0)
    handler.handle_event(_frame(EVENT_GPIO_VALUE, payload))
    assert len(seen) == 1
    assert seen[0].gpio == 6


def test_handler_multiple_callbacks():
    handler = EventHandler()
    calls = []
    handler.register_callback(EVENT_GPIO_VALUE, lambda e: calls.append('a'))
    handler.register_callback(EVENT_GPIO_VALUE, lambda e: calls.append('b'))
    handler.handle_event(_frame(EVENT_GPIO_VALUE, struct.pack('<HBBq', 0, 1, 0, 0)))
    assert sorted(calls) == ['a', 'b']


def test_handler_unknown_opcode_ignored():
    handler = EventHandler()
    handler.handle_event(_frame(0x99, b'\x00'))
    assert 0x99 not in handler.pending_events


def test_handler_callback_exception_isolated():
    handler = EventHandler()
    hits = []

    def boom(_):
        raise RuntimeError("boom")

    handler.register_callback(EVENT_GPIO_VALUE, boom)
    handler.register_callback(EVENT_GPIO_VALUE, lambda e: hits.append(1))
    handler.handle_event(_frame(EVENT_GPIO_VALUE, struct.pack('<HBBq', 0, 1, 0, 0)))
    # second callback still runs despite first raising
    assert hits == [1]


def test_handler_wait_for_event_fifo():
    handler = EventHandler()
    handler.handle_event(_frame(EVENT_GPIO_VALUE, struct.pack('<HBBq', 0, 1, 0, 0)))
    handler.handle_event(_frame(EVENT_GPIO_VALUE, struct.pack('<HBBq', 0, 2, 0, 0)))
    first = handler.wait_for_event(EVENT_GPIO_VALUE, timeout=0.5)
    second = handler.wait_for_event(EVENT_GPIO_VALUE, timeout=0.5)
    assert first.gpio == 1
    assert second.gpio == 2


def test_handler_wait_for_event_matching():
    handler = EventHandler()
    handler.handle_event(_frame(EVENT_GPIO_VALUE, struct.pack('<HBBq', 0, 1, 0, 0)))
    handler.handle_event(_frame(EVENT_GPIO_VALUE, struct.pack('<HBBq', 0, 7, 1, 0)))
    ev = handler.wait_for_event_matching(
        EVENT_GPIO_VALUE, lambda e: e.gpio == 7, timeout=0.5)
    assert ev.gpio == 7


def test_handler_clear_pending():
    handler = EventHandler()
    handler.handle_event(_frame(EVENT_GPIO_VALUE, struct.pack('<HBBq', 0, 1, 0, 0)))
    handler.clear_pending()
    assert handler.wait_for_event(EVENT_GPIO_VALUE, timeout=0.1) is None


def test_handler_empty_payload_ignored():
    handler = EventHandler()
    frame = MessageFrame(version=1, msg_type=MSG_TYPE_EVENT, length=0,
                         cmd_id=0, crc=0, payload=b'')
    handler.handle_event(frame)  # must not raise
