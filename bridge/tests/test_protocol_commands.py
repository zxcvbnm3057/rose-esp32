"""Unit tests for command serialization (bridge/protocol.py).

These tests assert that every command dataclass serializes to the exact
byte layout expected by the firmware (`include/iot_agent.h`). No hardware
is required.
"""

import struct
import pytest

from ..src.protocol import (
    # opcodes
    CMD_GPIO_CONFIG,
    CMD_GPIO_SET,
    CMD_GPIO_GET,
    CMD_ADC_SAMPLE,
    CMD_GPIO_SIGNAL_TX,
    CMD_GPIO_SIGNAL_RX,
    CMD_GPIO_SIGNAL_EXCHANGE,
    CMD_UART_CONFIG,
    CMD_UART_SEND,
    CMD_UART_READ,
    CMD_PORT_BIND,
    CMD_PORT_UNBIND,
    CMD_PORT_STATUS,
    CMD_THREAD_PASSTHROUGH,
    CMD_SYNC_REQUEST,
    CMD_SYN,
    CMD_BLE_ENABLE_PAIRING,
    CMD_BLE_DISABLE_PAIRING,
    CMD_BLE_GET_PEERS,
    CMD_BLE_START_SCAN,
    CMD_BLE_STOP_SCAN,
    CMD_HEARTBEAT,
    CMD_PING,
    # command dataclasses
    CmdGpioConfig,
    CmdGpioSet,
    CmdGpioGet,
    CmdAdcSample,
    CmdGpioSignalTx,
    CmdGpioSignalRx,
    CmdGpioSignalExchange,
    CmdUartConfig,
    CmdUartSend,
    CmdUartRead,
    CmdPortBind,
    CmdPortUnbind,
    CmdPortStatus,
    CmdThreadPassthrough,
    CmdSyncRequest,
    CmdSyn,
    CmdHeartbeat,
    CmdBleEnablePairing,
    CmdBleDisablePairing,
    CmdBleGetPeers,
    CmdBleStartScan,
    CmdBleStopScan,
    RESOURCE_GPIO,
    RESOURCE_UART,
    GPIO_MODE_OUTPUT,
    GPIO_MODE_ADC,
    PULL_MODE_UP,
)


# ── Opcode value contract (must match firmware header) ──────────────────

def test_opcode_values():
    """Lock opcode constants to firmware include/iot_agent.h values."""
    assert CMD_GPIO_CONFIG == 0x10
    assert CMD_GPIO_SET == 0x11
    assert CMD_GPIO_GET == 0x12
    assert CMD_ADC_SAMPLE == 0x13
    assert CMD_GPIO_SIGNAL_TX == 0x14
    assert CMD_GPIO_SIGNAL_RX == 0x15
    assert CMD_GPIO_SIGNAL_EXCHANGE == 0x16
    assert CMD_UART_CONFIG == 0x20
    assert CMD_UART_SEND == 0x21
    assert CMD_UART_READ == 0x22
    assert CMD_PORT_BIND == 0x30
    assert CMD_PORT_UNBIND == 0x31
    assert CMD_PORT_STATUS == 0x32
    assert CMD_THREAD_PASSTHROUGH == 0x40
    assert CMD_SYNC_REQUEST == 0x01
    assert CMD_SYN == 0x02
    assert CMD_BLE_ENABLE_PAIRING == 0x50
    assert CMD_BLE_DISABLE_PAIRING == 0x51
    assert CMD_BLE_GET_PEERS == 0x52
    assert CMD_BLE_START_SCAN == 0x53
    assert CMD_BLE_STOP_SCAN == 0x54
    assert CMD_HEARTBEAT == 0xFE
    assert CMD_PING == 0xFF


# ── GPIO commands ───────────────────────────────────────────────────────

def test_gpio_config_layout():
    cmd = CmdGpioConfig(gpio=5, mode=GPIO_MODE_OUTPUT, pull=PULL_MODE_UP, edge=0)
    data = cmd.to_bytes()
    assert data == struct.pack('<BBBB', 5, GPIO_MODE_OUTPUT, PULL_MODE_UP, 0)
    assert len(data) == 4


def test_gpio_config_roundtrip():
    cmd = CmdGpioConfig(gpio=7, mode=2, pull=1, edge=3)
    restored = CmdGpioConfig.from_bytes(cmd.to_bytes())
    assert restored == cmd


def test_gpio_set_layout():
    cmd = CmdGpioSet(gpio=12, value=1)
    assert cmd.to_bytes() == struct.pack('<BB', 12, 1)


def test_gpio_get_layout():
    cmd = CmdGpioGet(gpio=6)
    assert cmd.to_bytes() == struct.pack('<B', 6)


def test_adc_sample_layout():
    cmd = CmdAdcSample(gpio=6, samples=4)
    assert cmd.to_bytes() == struct.pack('<BB', 6, 4)


# ── Signal commands ─────────────────────────────────────────────────────

def test_signal_tx_layout():
    edges = [(1, 100), (0, 200), (1, 150)]
    cmd = CmdGpioSignalTx(gpio=5, signal_len=len(edges), delay_us=50, signal_data=edges)
    data = cmd.to_bytes()
    # header: B gpio + H signal_len + I delay_us = 7 bytes, then 5 bytes/edge
    assert data[:7] == struct.pack('<BHI', 5, 3, 50)
    assert len(data) == 7 + 3 * 5
    # verify first edge
    level, dur = struct.unpack('<BI', data[7:12])
    assert (level, dur) == (1, 100)


def test_signal_rx_layout():
    cmd = CmdGpioSignalRx(gpio=4, timeout_us=1_000_000, max_edges=100)
    data = cmd.to_bytes()
    assert data == struct.pack('<BIH', 4, 1_000_000, 100)
    assert len(data) == 7


def test_signal_exchange_layout():
    edges = [(1, 100), (0, 200)]
    cmd = CmdGpioSignalExchange(
        gpio=5, tx_len=len(edges), delay_us=50,
        rx_total_us=1_000_000, rx_max_edges=100,
        tx_signal_data=edges)
    data = cmd.to_bytes()
    # header BHIIH = 1+2+4+4+2 = 13 bytes (resolution removed from the wire;
    # it's now a software-only concept in the bridge client).
    head = struct.pack('<BHIIH', 5, 2, 50, 1_000_000, 100)
    assert data[:13] == head
    assert len(data) == 13 + 2 * 5


def test_signal_exchange_empty_tx():
    cmd = CmdGpioSignalExchange(
        gpio=5, tx_len=0, delay_us=0,
        rx_total_us=500, rx_max_edges=10,
        tx_signal_data=[])
    data = cmd.to_bytes()
    assert len(data) == 13


def test_gpio_signal_exchange_frame_has_no_resolution():
    """rx_resolution_us was removed from the wire protocol: the firmware now
    always captures at finest resolution and the bridge client applies
    resolution in software.  The serialized exchange frame must therefore be
    exactly opcode + 13-byte header + tx payload, with no resolution field."""
    from ..src.commands import CommandDispatcher

    class _FakeServer:
        def __init__(self):
            self.last_frame = None

        def send_command(self, frame):
            self.last_frame = frame
            return True

    server = _FakeServer()
    disp = CommandDispatcher(server)
    cmd_id = disp.gpio_signal_exchange(
        gpio=5, tx_signal=[(1, 100), (0, 200)],
        delay_us=50, rx_total_us=1_000_000, rx_max_edges=100)
    assert cmd_id is not None
    payload = server.last_frame.payload
    assert payload[0] == CMD_GPIO_SIGNAL_EXCHANGE
    # opcode(1) + header(13) + 2 edges * 5 bytes = 24 bytes total.
    assert len(payload) == 1 + 13 + 2 * 5
    _gpio, _txlen, _delay, _rxtot, _rxedges = struct.unpack('<BHIIH', payload[1:14])
    assert _gpio == 5 and _txlen == 2 and _rxtot == 1_000_000


# ── UART commands ───────────────────────────────────────────────────────

def test_uart_config_layout():
    cmd = CmdUartConfig(uart_id=0, baudrate=115200, data_bits=8,
                        parity=0, stop_bits=1, tx_gpio=1, rx_gpio=3)
    data = cmd.to_bytes()
    assert data == struct.pack('<BIBBBBB', 0, 115200, 8, 0, 1, 1, 3)
    assert len(data) == 10


def test_uart_send_layout():
    payload = b'HELLO'
    cmd = CmdUartSend(uart_id=0, length=len(payload), data=payload)
    data = cmd.to_bytes()
    assert data[:3] == struct.pack('<BH', 0, 5)
    assert data[3:] == payload


def test_uart_read_layout():
    cmd = CmdUartRead(uart_id=1, length=256)
    assert cmd.to_bytes() == struct.pack('<BH', 1, 256)


# ── Port commands ───────────────────────────────────────────────────────

def test_port_bind_layout():
    cmd = CmdPortBind(resource_type=RESOURCE_GPIO, id=5, owner_id=42)
    data = cmd.to_bytes()
    assert data == struct.pack('<BBH', RESOURCE_GPIO, 5, 42)


def test_port_unbind_layout():
    cmd = CmdPortUnbind(resource_type=RESOURCE_UART, id=1)
    assert cmd.to_bytes() == struct.pack('<BB', RESOURCE_UART, 1)


def test_port_status_layout():
    cmd = CmdPortStatus(resource_type=RESOURCE_GPIO, id=6)
    assert cmd.to_bytes() == struct.pack('<BB', RESOURCE_GPIO, 6)


# ── Thread / sync commands ──────────────────────────────────────────────

def test_thread_passthrough_layout():
    payload = b'\xde\xad\xbe\xef'
    cmd = CmdThreadPassthrough(device_id=7, payload_len=len(payload),
                               correlation_id=0x12345678, payload=payload)
    data = cmd.to_bytes()
    assert data[:8] == struct.pack('<HHI', 7, 4, 0x12345678)
    assert data[8:] == payload


def test_sync_request_empty():
    assert CmdSyncRequest().to_bytes() == b''


def test_syn_layout():
    cmd = CmdSyn(correlation_id=0xAABBCCDD, stage=1)
    assert cmd.to_bytes() == struct.pack('<IB', 0xAABBCCDD, 1)


def test_heartbeat_layout():
    cmd = CmdHeartbeat(timestamp=1_700_000_000)
    assert cmd.to_bytes() == struct.pack('<I', 1_700_000_000)


def test_heartbeat_masks_to_u32():
    cmd = CmdHeartbeat(timestamp=0x1_FFFF_FFFF)
    assert cmd.to_bytes() == struct.pack('<I', 0xFFFF_FFFF)


# ── BLE commands ────────────────────────────────────────────────────────

def test_ble_enable_pairing_layout():
    cmd = CmdBleEnablePairing(timeout_s=60)
    assert cmd.to_bytes() == struct.pack('<I', 60)


def test_ble_disable_pairing_layout():
    cmd = CmdBleDisablePairing(reason=2)
    assert cmd.to_bytes() == struct.pack('<B', 2)


def test_ble_get_peers_empty():
    assert CmdBleGetPeers().to_bytes() == b''


def test_ble_start_scan_layout():
    cmd = CmdBleStartScan(interval_s=5)
    assert cmd.to_bytes() == struct.pack('<I', 5)


def test_ble_stop_scan_empty():
    assert CmdBleStopScan().to_bytes() == b''
