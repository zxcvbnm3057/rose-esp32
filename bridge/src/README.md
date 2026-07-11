# IoT Agent Python Bridge

Complete Python implementation for controlling ESP32 IoT Agent devices over TCP/IP.

## Overview

The IoT Agent Bridge provides:
- **TCP Server**: Listen for ESP32 connections
- **Command Interface**: All 25 ESP32 commands fully typed
- **Event Handler**: Parse and process all event types
- **Type Hints**: 100% type annotated with Python 3.8+ compatibility

## Installation

```bash
# Use provided conda environment
export PATH=/path/to/.conda/bin:$PATH
python -m pip install -e bridge/
```

## Quick Start

### Basic GPIO Control

```python
from bridge.client import IoTAgentClient
from bridge.protocol import GPIO_MODE_OUTPUT, GPIO_MODE_INPUT

client = IoTAgentClient(host='192.168.1.100', port=8080)
client.start()

# Wait for device connection
if client.wait_for_connection(timeout=60.0):
    # Configure GPIO 5 as output
    client.configure_gpio(5, GPIO_MODE_OUTPUT)
    
    # Set GPIO 5 high
    client.set_gpio(5, 1)
    
    # Read GPIO 6 value
    value = client.get_gpio(6)
    print(f"GPIO 6: {value}")

client.stop()
```

### Signal Exchange (TX + RX)

```python
# Send signal sequence and capture response (using GPIO 5↔4 loopback)
tx_signal = [(1, 100), (0, 200), (1, 150)]  # level, duration_us

result = client.exchange_signals(
    gpio=5,              # TX pin (multiplexed with GPIO 4 for loopback)
    tx_signal=tx_signal,
    delay_us=50,         # Wait 50µs after TX before RX
    rx_total_us=1000000  # Capture for 1ms max
)

if result:
    print(f"Captured {len(result)} edges:")
    for level, duration_us in result:
        print(f"  {level} for {duration_us}µs")
```

### BLE Operations

```python
# Enable pairing for 60 seconds
client.enable_ble_pairing(timeout_s=60)
print("Pairing enabled, waiting for device...")

# Query devices currently in range
devices = client.get_ble_in_range()
for device in devices:
    print(f"Device: {device['mac'].hex()}, RSSI: {device['rssi']} dBm")

# Disable pairing
client.disable_ble_pairing()
```

### UART Communication

```python
# Configure UART 0 self-loopback (GPIO1 TX ↔ GPIO3 RX)
client.configure_uart(uart_id=0, baudrate=115200, tx_gpio=1, rx_gpio=3)

# Send data (will loop back through hardware connection)
client.send_uart(0, b'Hello UART Loopback!')

# Read response (receives the same data due to loopback)
response = client.read_uart(0, length=256)
print(f"Loopback response: {response.decode()}")
```

## Architecture

### Layer 1: Protocol (`protocol.py`)

Message framing, serialization, and all data structures.

```python
from bridge.protocol import MessageFrame, CMD_GPIO_CONFIG, GPIO_MODE_OUTPUT

# Create and serialize command
payload = struct.pack('<BBBB', 5, GPIO_MODE_OUTPUT, PULL_MODE_UP, 0)
frame = MessageFrame(
    version=1,
    msg_type=MSG_TYPE_CMD,
    length=len(payload),
    cmd_id=1,
    crc=0,
    payload=bytes([CMD_GPIO_CONFIG]) + payload
)
frame.crc = frame.calculate_crc()
data = frame.to_bytes()  # 8 byte header + payload
```

### Layer 2: Server (`server.py`)

TCP server accepting ESP32 connections.

```python
from bridge.server import IoTAgentServer

server = IoTAgentServer(host='0.0.0.0', port=8080)
server.start()

# Register event callback
def on_event(frame):
    print(f"Event: {frame.cmd_id}")
    
server.set_event_callback(on_event)

# Send command
server.send_command(frame)

server.stop()
```

### Layer 3: Commands (`commands.py`)

Type-safe command builders.

```python
from bridge.commands import CommandDispatcher

dispatcher = CommandDispatcher(server)

# All 25 commands available
cmd_id = dispatcher.gpio_config(5, GPIO_MODE_OUTPUT)
cmd_id = dispatcher.gpio_set(5, 1)
cmd_id = dispatcher.adc_sample(2, samples=4)
cmd_id = dispatcher.gpio_signal_exchange(...)
cmd_id = dispatcher.uart_send(0, b'hello')
cmd_id = dispatcher.ble_enable_pairing(60)
# ... and more
```

### Layer 4: Client (`client.py`)

High-level convenience interface.

```python
from bridge.client import IoTAgentClient

client = IoTAgentClient()
client.start()

# Direct operations with automatic ACK waiting
client.configure_gpio(5, GPIO_MODE_OUTPUT)
client.set_gpio(5, 1)
value = client.get_gpio(6)

client.stop()
```

## Command Opcodes (Downlink)

The single source of truth for all opcodes is the firmware header
`include/iot_agent.h`; `bridge/protocol.py` mirrors it exactly.

| ID | Command | Group | Purpose |
|----|---------|-------|---------|
| 0x01 | CMD_SYNC_REQUEST | Sync | Request device state snapshot after reconnect |
| 0x02 | CMD_SYN | Sync | Confirm receipt of an ACK / downstream result |
| 0x10 | CMD_GPIO_CONFIG | GPIO | Configure pin mode/pull/edge |
| 0x11 | CMD_GPIO_SET | GPIO | Set output level |
| 0x12 | CMD_GPIO_GET | GPIO | Read input level |
| 0x13 | CMD_ADC_SAMPLE | GPIO | Sample ADC channel |
| 0x14 | CMD_GPIO_SIGNAL_TX | Signal | Transmit RMT sequence |
| 0x15 | CMD_GPIO_SIGNAL_RX | Signal | Capture GPIO edges |
| 0x16 | CMD_GPIO_SIGNAL_EXCHANGE | Signal | TX + delay + RX |
| 0x20 | CMD_UART_CONFIG | UART | Initialize UART |
| 0x21 | CMD_UART_SEND | UART | Send data |
| 0x22 | CMD_UART_READ | UART | Poll-read data (loopback/compat) |
| 0x30 | CMD_PORT_BIND | Port | Acquire resource |
| 0x31 | CMD_PORT_UNBIND | Port | Release resource |
| 0x32 | CMD_PORT_STATUS | Port | Query status |
| 0x40 | CMD_THREAD_PASSTHROUGH | Thread | Forward to downstream device |
| 0x50 | CMD_BLE_ENABLE_PAIRING | BLE | Start pairing (timeout_s) |
| 0x51 | CMD_BLE_DISABLE_PAIRING | BLE | Stop pairing (reason) |
| 0x52 | CMD_BLE_GET_IN_RANGE | BLE | List devices currently in range |
| 0x53 | CMD_BLE_START_SCAN | BLE | Start RSSI scan (interval_s) |
| 0x54 | CMD_BLE_STOP_SCAN | BLE | Stop RSSI scan |
| 0xFE | CMD_HEARTBEAT | System | Host-initiated keepalive (timestamp) |
| 0xFF | CMD_PING | System | Echo / liveness check |

> Note: `CMD_SYNC_REQUEST` (0x01) and `CMD_SYN` (0x02) reuse low opcode
> values that do not collide with the 0x10+ functional commands. They are
> distinguished by the message framing and dispatch path on the device.

## Event Opcodes (Uplink)

| ID | Event | Group | Payload summary |
|----|-------|-------|-----------------|
| 0x20 | EVENT_CMD_ACK | System | cmd_id, status, error_code, correlation_id |
| 0x21 | EVENT_GPIO_VALUE | GPIO | gpio, value, timestamp_us |
| 0x22 | EVENT_GPIO_EDGE | GPIO | gpio, edge_type, timestamp_us (INTERRUPT mode) |
| 0x23 | EVENT_ADC_VALUE | GPIO | gpio, value, timestamp_us |
| 0x24 | EVENT_GPIO_SIGNAL_CAPTURED | Signal | gpio, edge_count, timestamp_us, N×(level,duration_us) |
| 0x30 | EVENT_UART_RX | UART | uart_id, length, timestamp_us, data |
| 0x31 | EVENT_UART_STATUS | UART | full UART config snapshot (for sync) |
| 0x40 | EVENT_THREAD_RESPONSE | Thread | device_id, correlation_id, timestamp_us, payload |
| 0x50 | EVENT_PORT_STATUS | Port | resource_type, id, mode, owner, in_use, value |
| 0x51 | EVENT_GPIO_STATUS | GPIO | full GPIO snapshot: mode/pull/edge/value/adc (for sync) |
| 0x60 | EVENT_BLE_PAIRING_ENABLED | BLE | pin_code[6], timeout_s |
| 0x61 | EVENT_BLE_PAIRING_DISABLED | BLE | reason (0=other,1=timeout,2=paired) |
| 0x62 | EVENT_BLE_DEVICE_IN_RANGE | BLE | device_mac[6], rssi |
| 0x63 | EVENT_BLE_DEVICE_OUT_OF_RANGE | BLE | device_mac[6], reason |
| 0x64 | EVENT_BLE_IN_RANGE_LIST | BLE | device_count + N×(mac[6], rssi) |
| 0x65 | EVENT_BLE_RSSI | BLE | device_mac[6], rssi, timestamp_us |
| 0x66 | EVENT_SYNC_RESPONSE | Sync | session_version + pending/port counts |
| 0x67 | EVENT_BLE_STATUS | BLE | pairing_enabled, scan_enabled, device_count, timeout_s |
| 0xFD | EVENT_HEARTBEAT | System | timestamp, connection_state |
| 0xFE | EVENT_ERROR | System | cmd_id, err_code, message |

### GPIO / UART guard semantics

- `CMD_GPIO_SET` must only succeed when the target GPIO is already bound as GPIO and its mode is `OUTPUT` or `INPUT_OUTPUT`.
- A GPIO currently occupied by a UART `TX/RX` binding must reject `CMD_GPIO_SET`.
- `CMD_UART_SEND` and `CMD_UART_READ` must reject unbound / incompletely configured UARTs.

## Reliability: cmd / ack / syn flow

`cmd_id` is the transport-level frame ID used for retransmission matching.
`correlation_id` is the business-level key that ties a request, its
`EVENT_CMD_ACK`, any downstream `EVENT_THREAD_RESPONSE`, and the final
`CMD_SYN` together.

- Most commands (GPIO/UART/port/BLE) reply with `EVENT_CMD_ACK` immediately
  and are not buffered (port-bind idempotency relies on state queries, see
  `iot_design.md` §9.5).
- `CMD_THREAD_PASSTHROUGH` is the only command that carries an explicit
  `correlation_id` and follows the full cmd → ack → syn → response → syn flow.
- After a reconnect, the host should send `CMD_SYNC_REQUEST`; the device
  replies with `EVENT_SYNC_RESPONSE` plus the retained BLE/thread/port data.

## Testing

Run protocol/event unit tests (no hardware required) from the project root:

```bash
python -m pytest bridge/tests/test_bridge_protocol.py -v
python -m pytest bridge/tests/test_bridge_events.py -v
```

Hardware tests (real ESP32) require `USE_REAL_DEVICE=1`:

```bash
USE_REAL_DEVICE=1 python -m pytest bridge/tests/test_gpio.py -v
USE_REAL_DEVICE=1 python -m pytest bridge/tests/test_signal.py -v
USE_REAL_DEVICE=1 python -m pytest bridge/tests/test_integration.py -v
```

## Hardware Setup

See `tests/HARDWARE_SETUP.md` for complete setup instructions. The minimal configuration requires:

- **3 DuPont wires** for GPIO connections
- **1 potentiometer** (10KΩ) for ADC testing
- **ESP32 board** with BLE support

### Minimal Connections

```
ESP32 GPIO connections:
GPIO 5 ────────────────── GPIO 4  (Multiplexed: GPIO + Signal testing)
GPIO 1 ────────────────── GPIO 3  (UART self-loopback)
GPIO 6 ───────────┬───── Potentiometer wiper
                  │
3.3V ──[10KΩ Pot]──┴──── GND
```

This setup enables testing of all 25 commands with maximum hardware reuse.

## Protocol Details

### Message Frame

```
Byte 0:       Version (1)
Byte 1:       Type (0x01=CMD, 0x02=ACK, 0x03=EVENT, 0x04=ERROR)
Bytes 2-3:    Payload length (little-endian u16)
Bytes 4-5:    Command ID (little-endian u16)
Bytes 6-7:    CRC16 (little-endian u16)
Bytes 8+...:  Payload (opcode + data)
```

### CRC16 Algorithm

- Initial: 0xFFFF
- Polynomial: 0xA001 (reflected)
- Input: Header (8 bytes) + Payload

### Signal Format

Each signal edge: `(level: u8, duration_us: u32)`
- level: 0=LOW or 1=HIGH
- duration_us: Edge duration in microseconds

## Error Handling

All commands return `Optional[int]` (command ID) or `Optional[bytes]` (data).

```python
# Proper error handling
cmd_id = client.commands.gpio_config(5, GPIO_MODE_OUTPUT)
if cmd_id is None:
    print("Command send failed")
    return

response = client.events.wait_for_response(cmd_id, timeout=2.0)
if response is None:
    print("Command timeout")
    return
```

## Type Annotations

100% type hints for IDE support:

```python
from bridge.client import IoTAgentClient
from bridge.protocol import GPIO_MODE_OUTPUT

client: IoTAgentClient = IoTAgentClient()
result: bool = client.configure_gpio(5, GPIO_MODE_OUTPUT)
value: Optional[int] = client.get_gpio(6)
signal: Optional[List[Tuple[int, int]]] = client.exchange_signal(7, [(1, 100)])
```

## Performance

- Frame serialization: <1µs
- CRC calculation: <1µs  
- CommandDispatcher overhead: <100µs
- Network latency: ~10-50ms typical

## Dependencies

- Python 3.8+
- stdlib only (no external packages required)

## License

See LICENSE.txt in project root.

## Contributing

See CONTRIBUTING.md for development guidelines.

## References

- Full API docs: `bridge/API.md`
- Protocol spec: `iot_design.md`
- Hardware setup: `tests/HARDWARE_SETUP.md`
- Protocol source: `bridge/protocol.py`

- **IoTAgentClient**: High-level client combining all components

### Message Protocol

The bridge uses a custom binary protocol with CRC16 validation:

```
Frame Structure:
- Version (1 byte)
- Message Type (1 byte)
- Length (2 bytes)
- Command ID (2 bytes)
- CRC16 (2 bytes)
- Payload (variable)
```

## API Reference

### IoTAgentClient

#### Initialization
```python
client = IoTAgentClient(host='0.0.0.0', port=8080)
```

#### Connection Management
```python
client.start()                    # Start TCP server
client.stop()                     # Stop server
client.is_connected()             # Check connection status
client.wait_for_connection(timeout=60.0)  # Wait for ESP32
```

#### GPIO Operations
```python
# Configuration
client.configure_gpio(gpio, mode, pull=0, edge=0)

# Digital I/O
client.set_gpio(gpio, value)      # Set output
client.get_gpio(gpio)             # Read input

# ADC
client.read_adc(gpio, samples=1)  # Read analog value

# Modes:
# 0: INPUT, 1: OUTPUT, 2: INTERRUPT, 3: ADC, 4: SIGNAL
```

#### Signal Operations
```python
# Send signal sequence
client.send_signal(gpio, [(level, duration_us), ...], delay_us=0)

# Receive signal
signal = client.receive_signal(gpio, timeout_us=1000000, max_edges=100)

# Exchange signals (TX + RX)
rx_signal = client.exchange_signals(
    gpio, tx_signal, delay_us=0,
    rx_total_us=1000000, rx_max_edges=100
)
```

#### UART Operations
```python
# Configure UART
client.configure_uart(uart_id, baudrate, tx_gpio=1, rx_gpio=3)

# Send/Receive data
client.send_uart(uart_id, data)
received = client.read_uart(uart_id, length=256)
```

#### BLE Operations
```python
# Pairing
pin = client.enable_ble_pairing(timeout_s=60)
client.disable_ble_pairing()

# In-range device query
devices = client.get_ble_in_range()

# RSSI scanning
client.start_ble_scan(interval_s=5)
```

#### System Operations
```python
client.ping()           # Test connectivity
client.heartbeat()      # Send heartbeat
```

### Low-Level Components

#### IoTAgentServer
```python
server = IoTAgentServer(host, port)
server.set_event_callback(callback)
server.send_command(frame)
```

#### CommandDispatcher
```python
dispatcher = CommandDispatcher(server)
cmd_id = dispatcher.gpio_config(gpio, mode)
```

#### EventHandler
```python
handler = EventHandler()
response = handler.wait_for_response(cmd_id, timeout=5.0)
```

## Testing

### Running Tests

```bash
# Install test dependencies
pip install pytest

# Run all tests
pytest tests/

# Run specific test
pytest tests/test_gpio.py::TestGPIOOperations::test_gpio_output
```

### Test Categories

- **test_basic.py**: Connection and basic commands
- **test_gpio.py**: GPIO input/output and ADC
- **test_signal.py**: Signal transmission and reception
- **test_ble.py**: BLE pairing and peer management
- **test_integration.py**: Full system workflows

### Hardware Testing Requirements

For signal loopback tests, connect GPIO pins on the ESP32 board:

```
ESP32 GPIO Connections for Testing:
- GPIO 5 (TX) <-> GPIO 4 (RX) for signal loopback
- GPIO 5 (OUT) <-> GPIO 4 (IN) for digital loopback
- ADC input on GPIO 6 (connect to voltage divider)
```

### Test Configuration

Tests assume ESP32 is connected and configured. Modify test fixtures for different setups:

```python
@pytest.fixture
def client(self):
    client = IoTAgentClient('192.168.1.100', 8080)  # ESP32 IP
    # ... connection logic
```

## Error Handling

The bridge provides comprehensive error handling:

- **Connection errors**: Automatic reconnection
- **Command timeouts**: Configurable timeout parameters
- **Invalid responses**: Graceful error reporting
- **Resource conflicts**: Proper error codes

## Performance

Typical performance metrics:
- Command latency: < 10ms
- GPIO operations: > 100 ops/sec
- Signal processing: Supports 1000+ edges
- TCP throughput: Limited by ESP32 capabilities

## Type Safety

All APIs are fully type-annotated for IDE support and static analysis:

```python
from typing import Optional, List, Tuple

def configure_gpio(self, gpio: int, mode: int, pull: int = 0, edge: int = 0) -> bool:
    ...

def exchange_signals(self, gpio: int, tx_signal: List[Tuple[int, int]],
                    delay_us: int = 0, rx_total_us: int = 1000000,
                    rx_max_edges: int = 100) -> Optional[List[Tuple[int, int]]]:
    ...
```

## Contributing

1. Follow type annotation standards
2. Add comprehensive tests
3. Update documentation
4. Maintain backward compatibility

## License

This project is open source. See LICENSE file for details.