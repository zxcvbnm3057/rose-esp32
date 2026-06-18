"""
Bridge API Documentation for IoT Agent

This module provides complete API documentation for using the Python bridge
to communicate with ESP32 IoT Agent systems.
"""

# IoT Agent Python Bridge - API Documentation

## Overview

The Python bridge provides a complete implementation for communicating with ESP32 IoT Agent devices via TCP/IP. It handles all commands and their associated event responses, with full type hints and error handling. The opcode set is defined in the firmware header `include/iot_agent.h` and mirrored in `bridge/protocol.py`.

## Installation & Setup

### Environment

```bash
# Use the provided conda environment
conda activate /path/to/.conda

# Required packages
pip install python-dateutil
```

### Quick Start

```python
from bridge.client import IoTAgentClient

# Create client and connect
client = IoTAgentClient(host='192.168.1.100', port=8080)
client.start()
client.wait_for_connection(timeout=60.0)

# Use client
client.configure_gpio(5, GPIO_MODE_OUTPUT)
client.set_gpio(5, 1)
value = client.get_gpio(5)

# Clean up
client.stop()
```

---

## Protocol Layer (`bridge/protocol.py`)

### Core Classes

#### `MessageFrame`

Base message frame class supporting all command/event types.

```python
@dataclass
class MessageFrame:
    version: int          # Protocol version (typically 1)
    msg_type: int         # MSG_TYPE_CMD, MSG_TYPE_EVENT, etc.
    length: int           # Payload length in bytes
    cmd_id: int           # Command/response ID (1-65535)
    crc: int              # CRC16 checksum
    payload: bytes        # Raw payload data

    @classmethod
    def from_bytes(data: bytes) -> MessageFrame:
        """Deserialize from raw bytes."""

    def to_bytes() -> bytes:
        """Serialize to raw bytes (8 byte header + payload)."""

    def calculate_crc() -> int:
        """Calculate CRC16 (0xFFFF initial, 0xA001 polynomial)."""
```

### Constants

```python
# Message Types
MSG_TYPE_CMD = 0x01          # Downlink command
MSG_TYPE_EVENT = 0x03        # Uplink event

# GPIO Modes
GPIO_MODE_INPUT = 0          # Read-only input
GPIO_MODE_OUTPUT = 1         # Controlled output
GPIO_MODE_INTERRUPT = 2      # Edge-triggered interrupt
GPIO_MODE_ADC = 3            # Analog sampling
GPIO_MODE_SIGNAL = 4         # Precise timing signal I/O
GPIO_MODE_INPUT_OUTPUT = 5   # Read/write combined mode

# Resource Types
RESOURCE_GPIO = 0            # GPIO resource
RESOURCE_UART = 1            # UART resource

# Pull Modes
PULL_MODE_NONE = 0           # No pull resistor
PULL_MODE_DOWN = 1           # Internal pull-down
PULL_MODE_UP = 2             # Internal pull-up
```

### All 25 Opcodes

#### GPIO (4 pins/operations)

```python
CMD_GPIO_CONFIG = 0x10       # Configure pin mode, pull, edge
CMD_GPIO_SET = 0x11          # Set output value
CMD_GPIO_GET = 0x12          # Read input value
CMD_ADC_SAMPLE = 0x13        # Sample ADC channel
```

#### Precise Signals (3 operations)

```python
CMD_GPIO_SIGNAL_TX = 0x14          # Transmit RMT sequence
CMD_GPIO_SIGNAL_RX = 0x15          # Capture GPIO edges
CMD_GPIO_SIGNAL_EXCHANGE = 0x16    # TX + delay + RX combined
```

#### UART (3 operations)

```python
CMD_UART_CONFIG = 0x20             # Initialize UART
CMD_UART_SEND = 0x21               # Send data
CMD_UART_READ = 0x22               # Read pending data

Guard rules:
- `CMD_GPIO_SET` is valid only for GPIOs already bound in `OUTPUT` or `INPUT_OUTPUT` mode.
- GPIOs occupied by UART TX/RX bindings must reject `CMD_GPIO_SET`.
- `CMD_UART_SEND` / `CMD_UART_READ` require a fully bound UART.
```

#### Port/Resource (3 operations)

```python
CMD_PORT_BIND = 0x30               # Acquire resource ownership
CMD_PORT_UNBIND = 0x31             # Release resource
CMD_PORT_STATUS = 0x32             # Query resource status
```

#### Thread (1 operation)

```python
CMD_THREAD_PASSTHROUGH = 0x40      # Forward to Thread device
```

#### BLE (5 operations)

```python
CMD_BLE_ENABLE_PAIRING = 0x50      # Start pairing mode
CMD_BLE_DISABLE_PAIRING = 0x51     # Stop pairing mode
CMD_BLE_GET_PEERS = 0x52           # List connected devices
CMD_BLE_START_SCAN = 0x53          # Enable RSSI monitoring
CMD_BLE_STOP_SCAN = 0x54           # Disable RSSI monitoring
```

#### Sync / Reliability (2 operations)

```python
CMD_SYNC_REQUEST = 0x01            # Request state snapshot after reconnect
CMD_SYN = 0x02                     # Confirm receipt of ACK / downstream result
```

#### System (2 operations)

```python
CMD_HEARTBEAT = 0xFE               # Keepalive probe
CMD_PING = 0xFF                    # Echo request
```

#### Event Opcodes (uplink)

```python
EVENT_CMD_ACK = 0x20               # Command acknowledgement
EVENT_GPIO_VALUE = 0x21            # GPIO read result
EVENT_GPIO_EDGE = 0x22             # GPIO interrupt edge
EVENT_ADC_VALUE = 0x23             # ADC sample result
EVENT_GPIO_SIGNAL_CAPTURED = 0x24  # Captured signal edges
EVENT_UART_RX = 0x30               # UART received data
EVENT_UART_STATUS = 0x31           # UART config snapshot (sync)
EVENT_THREAD_RESPONSE = 0x40       # Downstream device result
EVENT_PORT_STATUS = 0x50           # Port status reply
EVENT_GPIO_STATUS = 0x51           # GPIO config snapshot (sync)
EVENT_BLE_PAIRING_ENABLED = 0x60   # PIN + timeout
EVENT_BLE_PAIRING_DISABLED = 0x61  # reason
EVENT_BLE_PEER_CONNECTED = 0x62    # peer connected
EVENT_BLE_PEER_DISCONNECTED = 0x63 # peer disconnected
EVENT_BLE_PEERS_LIST = 0x64        # peer list
EVENT_BLE_RSSI = 0x65              # periodic RSSI
EVENT_SYNC_RESPONSE = 0x66         # state snapshot reply
EVENT_BLE_STATUS = 0x67            # BLE state snapshot (sync)
EVENT_HEARTBEAT = 0xFD             # heartbeat echo
EVENT_ERROR = 0xFE                 # error report
```

---

## Server Layer (`bridge/server.py`)

### `IoTAgentServer` Class

Handles TCP connections and frame processing.

```python
class IoTAgentServer:
    def __init__(self, host: str = '0.0.0.0', port: int = 8080) -> None:
        """Initialize server.
        
        Args:
            host: Listening address
            port: TCP port number
        """

    def start() -> None:
        """Start listening for connections."""

    def stop() -> None:
        """Stop server and close client socket."""

    def is_connected() -> bool:
        """Check if client is currently connected."""

    def send_command(frame: MessageFrame) -> bool:
        """Send command frame to connected client.
        
        Returns:
            True if sent successfully, False otherwise
        """

    def set_event_callback(callback: Callable[[MessageFrame], None]) -> None:
        """Register callback for incoming events.
        
        The callback receives deserialized MessageFrame objects.
        """
```

---

## Commands Layer (`bridge/commands.py`)

### `CommandDispatcher` Class

High-level command interface.

```python
class CommandDispatcher:
    def gpio_config(gpio: int, mode: int, pull: int = 0, edge: int = 0) -> Optional[int]:
        """Configure GPIO pin. Returns command ID or None on error."""

    def gpio_set(gpio: int, value: int) -> Optional[int]:
        """Set GPIO output value.

        Only valid for GPIO resources already bound as GPIO and configured as
        `OUTPUT` or `INPUT_OUTPUT`. GPIOs currently occupied by UART `TX/RX`
        bindings must be rejected.
        Returns command ID or None on error.
        """

    def gpio_get(gpio: int) -> Optional[int]:
        """Get GPIO input value. Returns command ID or None on error."""

    def adc_sample(gpio: int, samples: int = 1) -> Optional[int]:
        """Sample ADC channel. Returns command ID or None on error."""

    def gpio_signal_tx(gpio: int, signal: List[Tuple[int, int]], 
                       delay_us: int = 0) -> Optional[int]:
        """Transmit signal sequence.
        
        Args:
            gpio: GPIO pin number
            signal: List of (level, duration_us) tuples
            delay_us: Post-transmit delay before RX
            
        Returns:
            Command ID or None on error
        """

    def gpio_signal_rx(gpio: int, timeout_us: int = 1000000, 
                       max_edges: int = 100) -> Optional[int]:
        """Receive signal sequence.
        
        Args:
            gpio: GPIO pin number
            timeout_us: Maximum capture duration
            max_edges: Maximum edges to capture
            
        Returns:
            Command ID or None on error
        """

    def gpio_signal_exchange(gpio: int, tx_signal: List[Tuple[int, int]],
                             delay_us: int = 100,
                             rx_total_us: int = 1000000,
                             rx_max_edges: int = 32) -> Optional[int]:
        """Combined TX + delay + RX operation.
        
        Returns:
            Command ID or None on error
        """

    def uart_config(uart_id: int, baudrate: int = 115200,
                    data_bits: int = 8, parity: int = 0,
                    stop_bits: int = 1, tx_gpio: int = 1,
                    rx_gpio: int = 3) -> Optional[int]:
        """Configure UART. Returns command ID or None on error."""

    def uart_send(uart_id: int, data: bytes) -> Optional[int]:
        """Send UART data.

        Only valid for UART resources that are already fully configured/bound.
        Unbound or partially configured UARTs must be rejected.
        Returns command ID or None on error.
        """

    def uart_read(uart_id: int, length: int = 256) -> Optional[int]:
        """Read UART data.

        Only valid for UART resources that are already fully configured/bound.
        Unbound or partially configured UARTs must be rejected.
        Returns command ID or None on error.
        """

    def port_bind(resource_type: int, resource_id: int, 
                  owner_id: int) -> Optional[int]:
        """Acquire resource ownership. Returns command ID or None on error."""

    def port_unbind(resource_type: int, resource_id: int) -> Optional[int]:
        """Release resource. Returns command ID or None on error."""

    def port_status(resource_type: int, resource_id: int) -> Optional[int]:
        """Query resource status. Returns command ID or None on error."""

    def ble_enable_pairing(timeout_s: int = 60) -> Optional[int]:
        """Enable BLE pairing mode. Returns command ID or None on error."""

    def ble_disable_pairing() -> Optional[int]:
        """Disable BLE pairing mode. Returns command ID or None on error."""

    def ble_get_peers() -> Optional[int]:
        """List connected BLE peers. Returns command ID or None on error."""

    def ble_start_scan(interval_s: int = 5) -> Optional[int]:
        """Start RSSI scanning. Returns command ID or None on error."""

    def heartbeat(timestamp: int) -> Optional[int]:
        """Send heartbeat. Returns command ID or None on error."""

    def ping() -> Optional[int]:
        """Send ping. Returns command ID or None on error."""
```

---

## Events Layer (`bridge/events.py`)

### Event Handler Classes

All events inherit from base Event class with `from_bytes()` and `to_bytes()` methods.

```python
class Event:
    @classmethod
    def from_bytes(data: bytes) -> 'Event':
        """Deserialize from payload bytes."""
        
    def to_bytes() -> bytes:
        """Serialize to payload bytes."""
```

### Event Types (21 total)

```python
# Command responses
EVENT_CMD_ACK          # Command acknowledged/completed
EVENT_GPIO_VALUE       # GPIO read result
EVENT_GPIO_EDGE        # GPIO edge interrupt
EVENT_ADC_VALUE        # ADC sample result
EVENT_GPIO_SIGNAL_CAPTURED  # Signal RX result
EVENT_UART_RX          # UART received data
EVENT_THREAD_RESPONSE  # Thread device response
EVENT_PORT_STATUS      # Resource status
EVENT_ERROR            # Command error

# BLE events
EVENT_BLE_PAIRING_ENABLED      # Pairing started
EVENT_BLE_PAIRING_DISABLED     # Pairing stopped
EVENT_BLE_PEER_CONNECTED       # Device connected
EVENT_BLE_PEER_DISCONNECTED    # Device disconnected
EVENT_BLE_PEERS_LIST           # Connected peers list
EVENT_BLE_RSSI                 # RSSI measurement

# System
EVENT_HEARTBEAT                # Heartbeat response
```

---

## Client Layer (`bridge/client.py`)

### `IoTAgentClient` Class

High-level convenience interface combining all layers.

```python
class IoTAgentClient:
    def __init__(self, host: str = '0.0.0.0', port: int = 8080) -> None:
        """Initialize IoT Agent client."""

    def start() -> None:
        """Start server and connect to ESP32."""

    def stop() -> None:
        """Stop server and disconnect."""

    def is_connected() -> bool:
        """Check if ESP32 is connected."""

    def wait_for_connection(timeout: float = 10.0) -> bool:
        """Wait for ESP32 to connect."""

    # High-level GPIO operations
    def configure_gpio(gpio: int, mode: int, pull: int = 0) -> bool:
        """Configure GPIO pin and wait for ACK."""

    def set_gpio(gpio: int, value: int) -> bool:
        """Set GPIO value and wait for ACK."""

    def get_gpio(gpio: int) -> Optional[int]:
        """Read GPIO value (0 or 1)."""

    def read_adc(gpio: int, samples: int = 1) -> Optional[int]:
        """Read ADC value (0-4095)."""

    # Signal operations
    def send_signal(gpio: int, signal: List[Tuple[int, int]], 
                    delay_us: int = 0) -> bool:
        """Send GPIO signal sequence."""

    def receive_signal(gpio: int, timeout_us: int = 1000000,
                       max_edges: int = 100) -> Optional[List[Tuple[int, int]]]:
        """Receive GPIO signal sequence."""

    def exchange_signal(gpio: int, tx_signal: List[Tuple[int, int]],
                        delay_us: int = 100) -> Optional[List[Tuple[int, int]]]:
        """Combined TX and RX operation."""

    # UART operations
    def uart_send(uart_id: int, data: bytes) -> bool:
        """Send UART data."""

    def uart_read(uart_id: int, length: int = 256) -> Optional[bytes]:
        """Read pending UART data."""

    # BLE operations
    def enable_ble_pairing(timeout_s: int = 60) -> bool:
        """Enable BLE pairing mode."""

    def get_ble_peers() -> Optional[List[Tuple[bytes, int]]]:
        """Get list of connected BLE peers (MAC, RSSI)."""

    def start_ble_scan(interval_s: int = 5) -> bool:
        """Start BLE RSSI monitoring."""
```

---

## Typical Usage Patterns

### Pattern 1: GPIO Read/Write

```python
from bridge.client import IoTAgentClient
from bridge.protocol import GPIO_MODE_OUTPUT, GPIO_MODE_INPUT

client = IoTAgentClient('192.168.1.100', 8080)
client.start()
client.wait_for_connection()

# Configure pins
client.configure_gpio(5, GPIO_MODE_OUTPUT)
client.configure_gpio(6, GPIO_MODE_INPUT)

# Control and read
client.set_gpio(5, 1)  # Set HIGH
value = client.get_gpio(6)  # Read input

client.stop()
```

### Pattern 2: Signal Exchange (TX + RX)

```python
# Build signal: high 100µs, low 200µs, high 150µs
signal = [(1, 100), (0, 200), (1, 150)]

# Send and capture response
result = client.exchange_signal(
    gpio=7,
    tx_signal=signal,
    delay_us=50,  # Wait 50µs before capturing
)

if result:
    print(f"Captured {len(result)} edges")
    for level, duration in result:
        print(f"  Level {level} for {duration}µs")
```

### Pattern 3: UART Communication

```python
# Configure UART
client.uart_send(0, b'AT+RST\r\n')

# Read response
response = client.uart_read(0, length=256)
print(f"Received: {response.decode()}")
```

### Pattern 4: BLE Operations

```python
# Enable pairing
client.enable_ble_pairing(timeout_s=60)
print("Pairing enabled for 60 seconds...")

# After peer connects
peers = client.get_ble_peers()
for mac, rssi in peers:
    print(f"Peer {mac.hex()}: RSSI {rssi} dBm")
```

---

## Error Handling

All methods return `Optional` types or `bool`:
- `None` or `False` indicates failure
- Check `is_connected()` before operations
- Use `wait_for_connection()` to ensure ready state
- Events are queued; check event handler for errors

---

## Performance Characteristics

- **Command latency**: ~10-50ms typical
- **GPIO read/write**: <5ms
- **ADC sampling**: ~1-5ms per sample
- **Signal TX**: <100µs
- **Signal RX**: configurable up to seconds
- **Frame overhead**: 8 bytes + payload
- **CRC time**: <1µs

---

## Thread Safety

- All methods are thread-safe
- Event callbacks may be called from server thread
- Use locks when accessing shared state from callbacks

---

## References

- Protocol spec: `iot_design.md`
- Hardware setup: `tests/HARDWARE_SETUP.md`
- Examples: `tests/test_*.py`
