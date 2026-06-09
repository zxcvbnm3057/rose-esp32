"""
Command dispatcher for IoT Agent.

This module provides classes and methods for creating and sending commands
to the ESP32 IoT Agent.
"""

import time
import threading
from typing import List, Tuple, Optional, Dict
from .protocol import *
from .server import IoTAgentServer


class CommandDispatcher:
    """Dispatcher for sending commands to IoT Agent."""

    def __init__(self, server: IoTAgentServer) -> None:
        self.server = server
        self.next_cmd_id = 1
        self.pending_commands: Dict[int, dict] = {}
        self._lock = threading.Lock()

    def _get_next_cmd_id(self) -> int:
        """Get next command ID."""
        with self._lock:
            cmd_id = self.next_cmd_id
            self.next_cmd_id = (self.next_cmd_id + 1) % 65536
            if self.next_cmd_id == 0:
                self.next_cmd_id = 1
            return cmd_id

    def _send_command(self, opcode: int, payload: bytes) -> Optional[int]:
        """Send a command and return command ID."""
        cmd_id = self._get_next_cmd_id()

        frame = MessageFrame(
            version=1,
            msg_type=MSG_TYPE_CMD,
            length=len(payload) + 1,  # +1 for opcode
            cmd_id=cmd_id,
            crc=0,
            payload=bytes([opcode]) + payload)
        frame.crc = frame.calculate_crc()

        if self.server.send_command(frame):
            return cmd_id
        return None

    # GPIO Commands
    def gpio_config(self, gpio: int, mode: int, pull: int = 0, edge: int = 0) -> Optional[int]:
        """Configure GPIO pin."""
        cmd = CmdGpioConfig(gpio, mode, pull, edge)
        return self._send_command(CMD_GPIO_CONFIG, cmd.to_bytes())

    def gpio_set(self, gpio: int, value: int) -> Optional[int]:
        """Set GPIO output value."""
        cmd = CmdGpioSet(gpio, value)
        return self._send_command(CMD_GPIO_SET, cmd.to_bytes())

    def gpio_get(self, gpio: int) -> Optional[int]:
        """Get GPIO input value."""
        cmd = CmdGpioGet(gpio)
        return self._send_command(CMD_GPIO_GET, cmd.to_bytes())

    def adc_sample(self, gpio: int, samples: int = 1) -> Optional[int]:
        """Sample ADC on GPIO."""
        cmd = CmdAdcSample(gpio, samples)
        return self._send_command(CMD_ADC_SAMPLE, cmd.to_bytes())

    def gpio_signal_tx(self, gpio: int, signal_data: List[Tuple[int, int]], delay_us: int = 0) -> Optional[int]:
        """Send GPIO signal sequence."""
        cmd = CmdGpioSignalTx(gpio, len(signal_data), delay_us, signal_data)
        return self._send_command(CMD_GPIO_SIGNAL_TX, cmd.to_bytes())

    def gpio_signal_rx(self, gpio: int, timeout_us: int = 1000000, max_edges: int = 100) -> Optional[int]:
        """Receive GPIO signal."""
        cmd = CmdGpioSignalRx(gpio, timeout_us, max_edges)
        return self._send_command(CMD_GPIO_SIGNAL_RX, cmd.to_bytes())

    def gpio_signal_exchange(self,
                             gpio: int,
                             tx_signal: List[Tuple[int, int]],
                             delay_us: int = 0,
                             rx_total_us: int = 1000000,
                             rx_max_edges: int = 100,
                             rx_resolution_us: int = 1) -> Optional[int]:
        """Exchange GPIO signals (TX then RX)."""
        cmd = CmdGpioSignalExchange(gpio, len(tx_signal), delay_us, rx_total_us, rx_max_edges, rx_resolution_us,
                                    tx_signal)
        return self._send_command(CMD_GPIO_SIGNAL_EXCHANGE, cmd.to_bytes())

    # UART Commands
    def uart_config(self,
                    uart_id: int,
                    baudrate: int,
                    data_bits: int = 8,
                    parity: int = 0,
                    stop_bits: int = 1,
                    tx_gpio: int = 1,
                    rx_gpio: int = 3) -> Optional[int]:
        """Configure UART."""
        cmd = CmdUartConfig(uart_id, baudrate, data_bits, parity, stop_bits, tx_gpio, rx_gpio)
        return self._send_command(CMD_UART_CONFIG, cmd.to_bytes())

    def uart_send(self, uart_id: int, data: bytes) -> Optional[int]:
        """Send data via UART."""
        cmd = CmdUartSend(uart_id, len(data), data)
        return self._send_command(CMD_UART_SEND, cmd.to_bytes())

    def uart_read(self, uart_id: int, length: int = 256) -> Optional[int]:
        """Read data from UART."""
        cmd = CmdUartRead(uart_id, length)
        return self._send_command(CMD_UART_READ, cmd.to_bytes())

    # Port Management
    def port_bind(self, resource_type: int, id: int, owner_id: int = 0) -> Optional[int]:
        """Bind a port resource."""
        cmd = CmdPortBind(resource_type, id, owner_id)
        return self._send_command(CMD_PORT_BIND, cmd.to_bytes())

    def port_unbind(self, resource_type: int, id: int) -> Optional[int]:
        """Unbind a port resource."""
        cmd = CmdPortUnbind(resource_type, id)
        return self._send_command(CMD_PORT_UNBIND, cmd.to_bytes())

    def port_status(self, resource_type: int, id: int) -> Optional[int]:
        """Get port status."""
        cmd = CmdPortStatus(resource_type, id)
        return self._send_command(CMD_PORT_STATUS, cmd.to_bytes())

    # Thread Commands
    def thread_passthrough(self, device_id: int, payload: bytes, correlation_id: int = 0) -> Optional[int]:
        """Send Thread passthrough command."""
        cmd = CmdThreadPassthrough(device_id, len(payload), correlation_id, payload)
        return self._send_command(CMD_THREAD_PASSTHROUGH, cmd.to_bytes())

    def sync_request(self) -> Optional[int]:
        """Send a sync request to recover device state after reconnect."""
        cmd = CmdSyncRequest()
        return self._send_command(CMD_SYNC_REQUEST, cmd.to_bytes())

    def sync_confirm(self, correlation_id: int, stage: int = 0) -> Optional[int]:
        """Send a sync confirmation for a correlation ID."""
        cmd = CmdSyn(correlation_id, stage)
        return self._send_command(CMD_SYN, cmd.to_bytes())

    # BLE Commands
    def ble_enable_pairing(self, timeout_s: int = 60) -> Optional[int]:
        """Enable BLE pairing."""
        cmd = CmdBleEnablePairing(timeout_s)
        return self._send_command(CMD_BLE_ENABLE_PAIRING, cmd.to_bytes())

    def ble_disable_pairing(self, reason: int = 0) -> Optional[int]:
        """Disable BLE pairing."""
        cmd = CmdBleDisablePairing(reason)
        return self._send_command(CMD_BLE_DISABLE_PAIRING, cmd.to_bytes())

    def ble_get_peers(self) -> Optional[int]:
        """Get BLE peer list."""
        cmd = CmdBleGetPeers()
        return self._send_command(CMD_BLE_GET_PEERS, cmd.to_bytes())

    def ble_start_scan(self, interval_s: int = 5) -> Optional[int]:
        """Start BLE RSSI scan."""
        cmd = CmdBleStartScan(interval_s)
        return self._send_command(CMD_BLE_START_SCAN, cmd.to_bytes())

    def ble_stop_scan(self) -> Optional[int]:
        """Stop BLE RSSI scan."""
        cmd = CmdBleStopScan()
        return self._send_command(CMD_BLE_STOP_SCAN, cmd.to_bytes())

    # System Commands
    def ping(self) -> Optional[int]:
        """Send ping command."""
        return self._send_command(CMD_PING, b'')

    def heartbeat(self, timestamp: Optional[int] = None) -> Optional[int]:
        """Send heartbeat."""
        if timestamp is None:
            timestamp = int(time.time())  # seconds fits uint32 on device side
        cmd = CmdHeartbeat(timestamp)
        return self._send_command(CMD_HEARTBEAT, cmd.to_bytes())


