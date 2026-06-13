"""
Protocol definitions for IoT Agent communication.

This module defines the message frame structure, command/event opcodes,
and data structures used for communication between the Python bridge
and ESP32 IoT Agent.
"""

import struct
from typing import List, Tuple, Optional, Any
from dataclasses import dataclass

# Message types
MSG_TYPE_CMD: int = 0x01
MSG_TYPE_ACK: int = 0x02
MSG_TYPE_EVENT: int = 0x03
MSG_TYPE_ERROR: int = 0x04

# Command opcodes
CMD_GPIO_CONFIG: int = 0x10
CMD_GPIO_SET: int = 0x11
CMD_GPIO_GET: int = 0x12
CMD_ADC_SAMPLE: int = 0x13
CMD_GPIO_SIGNAL_TX: int = 0x14
CMD_GPIO_SIGNAL_RX: int = 0x15
CMD_GPIO_SIGNAL_EXCHANGE: int = 0x16
CMD_UART_CONFIG: int = 0x20
CMD_UART_SEND: int = 0x21
CMD_UART_READ: int = 0x22
CMD_PORT_BIND: int = 0x30
CMD_PORT_UNBIND: int = 0x31
CMD_PORT_STATUS: int = 0x32
CMD_THREAD_PASSTHROUGH: int = 0x40
CMD_SYNC_REQUEST: int = 0x01
CMD_SYN: int = 0x02
CMD_BLE_ENABLE_PAIRING: int = 0x50
CMD_BLE_DISABLE_PAIRING: int = 0x51
CMD_BLE_GET_PEERS: int = 0x52
CMD_BLE_START_SCAN: int = 0x53
CMD_BLE_STOP_SCAN: int = 0x54
CMD_HEARTBEAT: int = 0xFE
CMD_PING: int = 0xFF

# Event opcodes
EVENT_SYNC_RESPONSE: int = 0x66
EVENT_CMD_ACK: int = 0x20
EVENT_GPIO_VALUE: int = 0x21
EVENT_GPIO_EDGE: int = 0x22
EVENT_ADC_VALUE: int = 0x23
EVENT_GPIO_SIGNAL_CAPTURED: int = 0x24
EVENT_UART_RX: int = 0x30
EVENT_THREAD_RESPONSE: int = 0x40
EVENT_PORT_STATUS: int = 0x50
EVENT_BLE_PAIRING_ENABLED: int = 0x60
EVENT_BLE_PAIRING_DISABLED: int = 0x61
EVENT_BLE_PEER_CONNECTED: int = 0x62
EVENT_BLE_PEER_DISCONNECTED: int = 0x63
EVENT_BLE_PEERS_LIST: int = 0x64
EVENT_BLE_RSSI: int = 0x65
EVENT_ERROR: int = 0xFE
EVENT_HEARTBEAT: int = 0xFD

# Extended status events (for backend bridge_service)
# Must match firmware: include/iot_agent.h
EVENT_GPIO_STATUS: int = 0x51
EVENT_UART_STATUS: int = 0x31
EVENT_BLE_STATUS: int = 0x67

# GPIO modes
GPIO_MODE_INPUT: int = 0
GPIO_MODE_OUTPUT: int = 1
GPIO_MODE_INTERRUPT: int = 2
GPIO_MODE_ADC: int = 3
GPIO_MODE_SIGNAL: int = 4

# Pull modes
PULL_MODE_NONE: int = 0
PULL_MODE_DOWN: int = 1
PULL_MODE_UP: int = 2

# Resource types
RESOURCE_GPIO: int = 0
RESOURCE_UART: int = 1

# Error codes
IOT_ERR_INVALID_ARG: int = 1
IOT_ERR_INVALID_STATE: int = 2
IOT_ERR_DRIVER: int = 3
IOT_ERR_RESOURCE_CONFLICT: int = 4
IOT_ERR_UNSUPPORTED: int = 5
IOT_ERR_NOT_FOUND: int = 6
IOT_ERR_RESOURCE_EXHAUSTED: int = 7

# UART constants
UART_NUM_MAX: int = 2


@dataclass
class MessageFrame:
    """Message frame structure."""
    version: int
    msg_type: int
    length: int
    cmd_id: int
    crc: int
    payload: bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> 'MessageFrame':
        """Parse message frame from bytes."""
        if len(data) < 8:
            raise ValueError("Message too short")
        version: int
        msg_type: int
        length: int
        cmd_id: int
        crc: int
        version, msg_type, length, cmd_id, crc = struct.unpack('<BBHHH', data[:8])
        payload: bytes = data[8:8 + length] if length > 0 else b''
        return cls(version, msg_type, length, cmd_id, crc, payload)

    def to_bytes(self) -> bytes:
        """Serialize message frame to bytes."""
        header: bytes = struct.pack('<BBHHH', self.version, self.msg_type, self.length, self.cmd_id, self.crc)
        return header + self.payload

    def calculate_crc(self) -> int:
        """Calculate CRC16 for the message."""
        crc: int = 0xFFFF
        data: bytes = struct.pack('<BBHH', self.version, self.msg_type, self.length, self.cmd_id) + self.payload
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc


# Command structures
@dataclass
class CmdGpioConfig:
    gpio: int
    mode: int
    pull: int
    edge: int

    def to_bytes(self) -> bytes:
        return struct.pack('<BBBB', self.gpio, self.mode, self.pull, self.edge)

    @classmethod
    def from_bytes(cls, data: bytes) -> 'CmdGpioConfig':
        gpio, mode, pull, edge = struct.unpack('<BBBB', data)
        return cls(gpio, mode, pull, edge)


@dataclass
class CmdGpioSet:
    gpio: int
    value: int

    def to_bytes(self) -> bytes:
        return struct.pack('<BB', self.gpio, self.value)


@dataclass
class CmdGpioGet:
    gpio: int

    def to_bytes(self) -> bytes:
        return struct.pack('<B', self.gpio)


@dataclass
class CmdAdcSample:
    gpio: int
    samples: int

    def to_bytes(self) -> bytes:
        return struct.pack('<BB', self.gpio, self.samples)


@dataclass
class CmdGpioSignalTx:
    gpio: int
    signal_len: int
    delay_us: int
    signal_data: List[Tuple[int, int]]  # List of (level, duration_us)

    def to_bytes(self) -> bytes:
        data = struct.pack('<BHI', self.gpio, self.signal_len, self.delay_us)
        for level, duration in self.signal_data:
            data += struct.pack('<BI', level, duration)
        return data


@dataclass
class CmdGpioSignalRx:
    gpio: int
    timeout_us: int
    max_edges: int

    def to_bytes(self) -> bytes:
        return struct.pack('<BIH', self.gpio, self.timeout_us, self.max_edges)


@dataclass
class CmdGpioSignalExchange:
    gpio: int
    tx_len: int
    delay_us: int
    rx_total_us: int
    rx_max_edges: int
    tx_signal_data: List[Tuple[int, int]]

    def to_bytes(self) -> bytes:
        data = struct.pack('<BHIIH', self.gpio, self.tx_len, self.delay_us, self.rx_total_us, self.rx_max_edges)
        for level, duration in self.tx_signal_data:
            data += struct.pack('<BI', level, duration)
        return data


@dataclass
class CmdUartConfig:
    uart_id: int
    baudrate: int
    data_bits: int
    parity: int
    stop_bits: int
    tx_gpio: int
    rx_gpio: int

    def to_bytes(self) -> bytes:
        return struct.pack('<BIBBBBB', self.uart_id, self.baudrate, self.data_bits, self.parity, self.stop_bits,
                           self.tx_gpio, self.rx_gpio)


@dataclass
class CmdUartSend:
    uart_id: int
    length: int
    data: bytes

    def to_bytes(self) -> bytes:
        return struct.pack('<BH', self.uart_id, self.length) + self.data


@dataclass
class CmdUartRead:
    uart_id: int
    length: int

    def to_bytes(self) -> bytes:
        return struct.pack('<BH', self.uart_id, self.length)


@dataclass
class CmdPortBind:
    resource_type: int
    id: int
    owner_id: int

    def to_bytes(self) -> bytes:
        return struct.pack('<BBH', self.resource_type, self.id, self.owner_id)


@dataclass
class CmdPortUnbind:
    resource_type: int
    id: int

    def to_bytes(self) -> bytes:
        return struct.pack('<BB', self.resource_type, self.id)


@dataclass
class CmdPortStatus:
    resource_type: int
    id: int

    def to_bytes(self) -> bytes:
        return struct.pack('<BB', self.resource_type, self.id)


@dataclass
class CmdThreadPassthrough:
    device_id: int
    payload_len: int
    correlation_id: int
    payload: bytes

    def to_bytes(self) -> bytes:
        return struct.pack('<HHI', self.device_id, self.payload_len, self.correlation_id) + self.payload


@dataclass
class CmdSyncRequest:
    def to_bytes(self) -> bytes:
        return b''


@dataclass
class CmdSyn:
    correlation_id: int
    stage: int

    def to_bytes(self) -> bytes:
        return struct.pack('<IB', self.correlation_id, self.stage)


@dataclass
class CmdHeartbeat:
    timestamp: int

    def to_bytes(self) -> bytes:
        return struct.pack('<I', self.timestamp & 0xFFFFFFFF)


@dataclass
class CmdBleEnablePairing:
    timeout_s: int

    def to_bytes(self) -> bytes:
        return struct.pack('<I', self.timeout_s)


@dataclass
class CmdBleDisablePairing:
    reason: int

    def to_bytes(self) -> bytes:
        return struct.pack('<B', self.reason)


@dataclass
class CmdBleGetPeers:
    pass

    def to_bytes(self) -> bytes:
        return b''


@dataclass
class CmdBleStartScan:
    interval_s: int

    def to_bytes(self) -> bytes:
        return struct.pack('<I', self.interval_s)


@dataclass
class CmdBleStopScan:
    def to_bytes(self) -> bytes:
        return b''


# Event structures
@dataclass
class EventCmdAck:
    cmd_id: int
    status: int
    error_code: int
    correlation_id: int

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventCmdAck':
        cmd_id, status, error_code, correlation_id = struct.unpack('<HBBI', data)
        return cls(cmd_id, status, error_code, correlation_id)


@dataclass
class EventGpioValue:
    gpio: int
    value: int
    timestamp_us: int

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventGpioValue':
        fmt = '<BBQ'
        needed = struct.calcsize(fmt)
        if len(data) < needed:
            raise ValueError(f"EventGpioValue requires {needed} bytes, got {len(data)}")
        data = data[:needed]
        gpio, value, timestamp_us = struct.unpack(fmt, data)
        return cls(gpio, value, timestamp_us)


@dataclass
class EventGpioEdge:
    gpio: int
    edge_type: int
    timestamp_us: int

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventGpioEdge':
        fmt = '<BBQ'
        needed = struct.calcsize(fmt)
        if len(data) < needed:
            raise ValueError(f"EventGpioEdge requires {needed} bytes, got {len(data)}")
        data = data[:needed]
        gpio, edge_type, timestamp_us = struct.unpack(fmt, data)
        return cls(gpio, edge_type, timestamp_us)


@dataclass
class EventAdcValue:
    gpio: int
    value: int
    timestamp_us: int

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventAdcValue':
        if len(data) >= 16:
            # Compatibility with old firmware ABI padding:
            # [gpio(1)][pad(1)][value(2)][pad(4)][timestamp(8)]
            gpio = data[0]
            value = struct.unpack('<H', data[2:4])[0]
            timestamp_us = struct.unpack('<q', data[8:16])[0]
            return cls(gpio, value, timestamp_us)

        fmt = '<BHq'
        needed = struct.calcsize(fmt)
        if len(data) < needed:
            raise ValueError(f"EventAdcValue requires {needed} bytes, got {len(data)}")
        data = data[:needed]
        gpio, value, timestamp_us = struct.unpack(fmt, data)
        return cls(gpio, value, timestamp_us)


@dataclass
class SignalEdge:
    level: int
    duration_us: int


@dataclass
class EventGpioSignalCaptured:
    gpio: int
    edge_count: int
    timestamp_us: int
    edges: List[SignalEdge]

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventGpioSignalCaptured':
        gpio, edge_count, timestamp_us = struct.unpack('<BHq', data[:11])
        edges = []
        offset = 11
        for i in range(edge_count):
            level, duration_us = struct.unpack('<BI', data[offset:offset + 5])
            edges.append(SignalEdge(level, duration_us))
            offset += 5
        return cls(gpio, edge_count, timestamp_us, edges)


@dataclass
class EventUartRx:
    uart_id: int
    length: int
    timestamp_us: int
    data: bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventUartRx':
        uart_id, length, timestamp_us = struct.unpack('<BHq', data[:11])
        rx_data = data[11:11 + length]
        return cls(uart_id, length, timestamp_us, rx_data)


@dataclass
class EventThreadResponse:
    device_id: int
    payload_len: int
    correlation_id: int
    timestamp_us: int
    payload: bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventThreadResponse':
        device_id, payload_len, correlation_id, timestamp_us = struct.unpack('<HHIq', data[:16])
        payload = data[16:16 + payload_len]
        return cls(device_id, payload_len, correlation_id, timestamp_us, payload)


@dataclass
class EventSyncResponse:
    session_version: int
    pending_cmd_count: int
    pending_thread_count: int
    port_status_count: int

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventSyncResponse':
        session_version, pending_cmd_count, pending_thread_count, port_status_count = struct.unpack('<IHHH', data[:10])
        return cls(session_version, pending_cmd_count, pending_thread_count, port_status_count)


@dataclass
class EventPortStatus:
    resource_type: int
    id: int
    mode: int
    owner: int
    in_use: int
    value: int

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventPortStatus':
        resource_type, id, mode, owner, in_use, value = struct.unpack('<BBBHBB', data)
        return cls(resource_type, id, mode, owner, in_use, value)


@dataclass
class EventBlePairingEnabled:
    pin_code: bytes
    timeout_s: int

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventBlePairingEnabled':
        pin_code = data[:6]
        if len(data) >= 12:
            timeout_s = struct.unpack('<I', data[8:12])[0]
        else:
            timeout_s = struct.unpack('<I', data[6:10])[0]
        return cls(pin_code, timeout_s)


@dataclass
class EventBlePairingDisabled:
    reason: int

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventBlePairingDisabled':
        if len(data) < 1:
            raise ValueError("EventBlePairingDisabled requires at least 1 byte")
        return cls(data[0])


@dataclass
class EventBlePeersList:
    peer_count: int
    peers: List[Tuple[bytes, int]]

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventBlePeersList':
        if len(data) < 1:
            return cls(0, [])
        peer_count = data[0]
        peers: List[Tuple[bytes, int]] = []
        offset = 1
        for _ in range(peer_count):
            if offset + 7 > len(data):
                break
            mac = data[offset:offset + 6]
            rssi = struct.unpack('<b', data[offset + 6:offset + 7])[0]
            peers.append((mac, rssi))
            offset += 7
        return cls(peer_count, peers)


@dataclass
class EventBlePeerConnected:
    peer_mac: bytes
    rssi: int

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventBlePeerConnected':
        peer_mac = data[:6]
        rssi = struct.unpack('<b', data[6:7])[0]
        return cls(peer_mac, rssi)


@dataclass
class EventBlePeerDisconnected:
    peer_mac: bytes
    reason: int

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventBlePeerDisconnected':
        peer_mac = data[:6]
        reason = data[6] if len(data) > 6 else 0
        return cls(peer_mac, reason)


@dataclass
class EventBleRssi:
    peer_mac: bytes
    rssi: int
    timestamp_us: int

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventBleRssi':
        peer_mac = data[:6]
        rssi, timestamp_us = struct.unpack('<bq', data[6:15])
        return cls(peer_mac, rssi, timestamp_us)


@dataclass
class EventHeartbeat:
    timestamp: int
    connection_state: int

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventHeartbeat':
        if len(data) >= 8:
            # Compatibility with old firmware where structure had padding.
            timestamp = struct.unpack('<I', data[:4])[0]
            connection_state = data[4]
        else:
            timestamp, connection_state = struct.unpack('<IB', data)
        return cls(timestamp, connection_state)


@dataclass
class EventError:
    cmd_id: int
    err_code: int
    message: str

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventError':
        if len(data) >= 4:
            cmd_id, _status, err_code = struct.unpack('<HBB', data[:4])
            message = data[4:].decode('utf-8', errors='ignore')
        else:
            cmd_id, err_code = struct.unpack('<HB', data[:3])
            message = data[3:].decode('utf-8', errors='ignore')
        return cls(cmd_id, err_code, message)


# ── Extended status event structures (for backend) ──────────────────────

@dataclass
class EventUartStatus:
    uart_id: int
    baudrate: int
    data_bits: int
    parity: int
    stop_bits: int
    tx_gpio: int
    rx_gpio: int
    in_use: int
    owner: int

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventUartStatus':
        # Firmware struct: u8 uart_id, u32 baudrate, u8 data_bits, u8 parity,
        # u8 stop_bits, u8 tx_gpio, u8 rx_gpio, u8 in_use, u16 owner
        uart_id, baudrate, data_bits, parity, stop_bits, tx_gpio, rx_gpio, in_use, owner = \
            struct.unpack('<BIBBBBBBH', data[:14])
        return cls(uart_id, baudrate, data_bits, parity, stop_bits, tx_gpio, rx_gpio, in_use, owner)


@dataclass
class EventGpioStatus:
    gpio: int
    mode: int
    pull: int
    edge: int
    value: int
    in_use: int
    owner: int
    adc_raw: int
    adc_mv: int

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventGpioStatus':
        # Firmware struct: u8 gpio, u8 mode, u8 pull, u8 edge, u8 value,
        # u8 in_use, u16 owner, u16 adc_raw, u16 adc_mv
        gpio, mode, pull, edge, value, in_use, owner, adc_raw, adc_mv = \
            struct.unpack('<BBBBBBHHH', data[:14])
        return cls(gpio, mode, pull, edge, value, in_use, owner, adc_raw, adc_mv)


@dataclass
class EventBleStatus:
    pairing_enabled: int
    scan_enabled: int
    peer_count: int
    pairing_timeout_s: int

    @classmethod
    def from_bytes(cls, data: bytes) -> 'EventBleStatus':
        pairing_enabled, scan_enabled, peer_count, pairing_timeout_s = \
            struct.unpack('<BBBI', data[:7])
        return cls(pairing_enabled, scan_enabled, peer_count, pairing_timeout_s)
