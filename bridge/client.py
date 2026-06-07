"""
High-level client interface for IoT Agent.

This module provides a convenient client class that combines server,
command dispatcher, and event handler for easy interaction with
the ESP32 IoT Agent.
"""

import time
import logging
from queue import Queue, Empty
from typing import Optional, Any, List, Tuple, Dict
from .server import IoTAgentServer
from .commands import CommandDispatcher
from .events import EventHandler
from .protocol import EventCmdAck, EventGpioValue, EventAdcValue, EventGpioSignalCaptured, EventBlePairingEnabled, EventBlePeersList, EventHeartbeat, EventUartRx, EventSyncResponse
from .protocol import EVENT_SYNC_RESPONSE, EVENT_GPIO_VALUE, EVENT_ADC_VALUE, EVENT_GPIO_SIGNAL_CAPTURED, EVENT_UART_RX, EVENT_HEARTBEAT, EVENT_BLE_PEERS_LIST, EVENT_BLE_PAIRING_ENABLED, RESOURCE_GPIO

logger = logging.getLogger(__name__)


class UartRxListener:
    """Per-UART RX listener queue."""

    def __init__(self) -> None:
        self._queue = Queue()

    def put(self, data: bytes) -> None:
        self._queue.put(data)

    def read(self, timeout: float = 3.0) -> Optional[bytes]:
        try:
            return self._queue.get(timeout=timeout)
        except Empty:
            return None


class IoTAgentClient:
    """High-level client for IoT Agent communication."""

    def __init__(self, host: str = '0.0.0.0', port: int = 8080) -> None:
        self.server = IoTAgentServer(host, port)
        self.commands = CommandDispatcher(self.server)
        self.events = EventHandler()
        self._uart_listeners: Dict[int, UartRxListener] = {}

        # Connect event handler to server
        self.server.set_event_callback(self.events.handle_event)
        self.events.register_callback(EVENT_UART_RX, self._handle_uart_rx_event)

    def _handle_uart_rx_event(self, event: Any) -> None:
        if not isinstance(event, EventUartRx):
            return
        listener = self._uart_listeners.get(event.uart_id)
        if listener is not None:
            listener.put(event.data)

    def start(self) -> None:
        """Start the client (server)."""
        self.server.start()
        logger.info("IoT Agent Client started")

    def stop(self) -> None:
        """Stop the client."""
        self.server.stop()
        logger.info("IoT Agent Client stopped")

    def is_connected(self) -> bool:
        """Check if ESP32 is connected."""
        return self.server.is_connected()

    def wait_for_connection(self, timeout: float = 10.0) -> bool:
        """Wait for ESP32 to connect."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.is_connected():
                # Clear stale pending events from previous connection/disconnection
                self.events.clear_pending()
                # Wait a moment for device to fully initialize after connection
                time.sleep(0.2)
                return True
            time.sleep(0.1)
        return False

    # High-level GPIO operations
    def configure_gpio(self, gpio: int, mode: int = 0, pull: int = 0, edge: int = 0) -> bool:
        """Configure GPIO and wait for ACK."""
        cmd_id = self.commands.gpio_config(gpio, mode, pull, edge)
        if cmd_id is None:
            return False
        response = self.events.wait_for_response(cmd_id)
        if isinstance(response, EventCmdAck) and response.status == 0:
            return True

        # Retry once by unbinding stale GPIO ownership/state on device.
        unbind_id = self.commands.port_unbind(RESOURCE_GPIO, gpio)
        if unbind_id is not None:
            self.events.wait_for_response(unbind_id, timeout=1.0)
        retry_cmd_id = self.commands.gpio_config(gpio, mode, pull, edge)
        if retry_cmd_id is None:
            return False
        retry_response = self.events.wait_for_response(retry_cmd_id)
        return isinstance(retry_response, EventCmdAck) and retry_response.status == 0

    def set_gpio(self, gpio: int, value: int) -> bool:
        """Set GPIO value and wait for ACK."""
        cmd_id = self.commands.gpio_set(gpio, value)
        if cmd_id is None:
            return False
        response = self.events.wait_for_response(cmd_id)
        return isinstance(response, EventCmdAck) and response.status == 0

    def get_gpio(self, gpio: int) -> Optional[int]:
        """Get GPIO value."""
        cmd_id = self.commands.gpio_get(gpio)
        if cmd_id is None:
            return None
        response = self.events.wait_for_event(EVENT_GPIO_VALUE, timeout=2.0)
        if isinstance(response, EventGpioValue):
            return response.value
        return None

    def read_adc(self, gpio: int, samples: int = 1) -> Optional[int]:
        """Read ADC value."""
        cmd_id = self.commands.adc_sample(gpio, samples)
        if cmd_id is None:
            return None
        response = self.events.wait_for_event(EVENT_ADC_VALUE, timeout=2.0)
        if isinstance(response, EventAdcValue):
            return response.value
        return None

    def send_signal(self, gpio: int, signal: List[Tuple[int, int]], delay_us: int = 0) -> bool:
        """Send GPIO signal sequence."""
        cmd_id = self.commands.gpio_signal_tx(gpio, signal, delay_us)
        if cmd_id is None:
            return False
        response = self.events.wait_for_response(cmd_id)
        return isinstance(response, EventCmdAck) and response.status == 0

    def receive_signal(self,
                       gpio: int,
                       timeout_us: int = 1000000,
                       max_edges: int = 100) -> Optional[List[Tuple[int, int]]]:
        """Receive GPIO signal."""
        cmd_id = self.commands.gpio_signal_rx(gpio, timeout_us, max_edges)
        if cmd_id is None:
            return None
        response = self.events.wait_for_event_matching(
            EVENT_GPIO_SIGNAL_CAPTURED,
            lambda e: isinstance(e, EventGpioSignalCaptured) and e.gpio == gpio,
            timeout=timeout_us / 1000000 + 2.0,
        )
        if isinstance(response, EventGpioSignalCaptured):
            edges = [(edge.level, edge.duration_us) for edge in response.edges]
            return edges if edges else None
        return None

    def exchange_signals(self,
                         gpio: int,
                         tx_signal: List[Tuple[int, int]],
                         delay_us: int = 0,
                         rx_total_us: int = 1000000,
                         rx_max_edges: int = 100) -> Optional[List[Tuple[int, int]]]:
        """Exchange signals (TX then RX)."""
        cmd_id = self.commands.gpio_signal_exchange(gpio, tx_signal, delay_us, rx_total_us, rx_max_edges)
        if cmd_id is None:
            return None
        response = self.events.wait_for_event_matching(
            EVENT_GPIO_SIGNAL_CAPTURED,
            lambda e: isinstance(e, EventGpioSignalCaptured) and e.gpio == gpio,
            timeout=rx_total_us / 1000000 + 2.0,
        )
        if isinstance(response, EventGpioSignalCaptured):
            edges = [(edge.level, edge.duration_us) for edge in response.edges]
            return edges if edges else None
        return None

    # UART operations
    def configure_uart(self, uart_id: int, baudrate: int, tx_gpio: int = 1, rx_gpio: int = 3) -> Optional[UartRxListener]:
        """Configure UART and return an RX listener queue on success."""
        cmd_id = self.commands.uart_config(uart_id, baudrate, tx_gpio=tx_gpio, rx_gpio=rx_gpio)
        if cmd_id is None:
            return None
        response = self.events.wait_for_response(cmd_id)
        if isinstance(response, EventCmdAck) and response.status == 0:
            listener = UartRxListener()
            self._uart_listeners[uart_id] = listener
            return listener
        return None

    def send_uart(self, uart_id: int, data: bytes) -> bool:
        """Send data via UART."""
        cmd_id = self.commands.uart_send(uart_id, data)
        if cmd_id is None:
            return False
        response = self.events.wait_for_response(cmd_id)
        return isinstance(response, EventCmdAck) and response.status == 0

    def read_uart(self, uart_id: int, length: int = 256) -> Optional[bytes]:
        """Read data from UART.

        Prefer using listener returned by configure_uart for event-driven RX.
        This method keeps compatibility with the legacy active-read command.
        """
        listener = self._uart_listeners.get(uart_id)
        if listener is not None:
            data = listener.read(timeout=3.0)
            if data is None:
                return None
            return data[:length]

        cmd_id = self.commands.uart_read(uart_id, length)
        if cmd_id is None:
            return None
        response = self.events.wait_for_event_matching(
            EVENT_UART_RX,
            lambda e: isinstance(e, EventUartRx) and e.uart_id == uart_id,
            timeout=3.0,
        )
        if isinstance(response, EventUartRx):
            return response.data
        return None

    # BLE operations
    def enable_ble_pairing(self, timeout_s: int = 60) -> Optional[bytes]:
        """Enable BLE pairing and return PIN."""
        cmd_id = self.commands.ble_enable_pairing(timeout_s)
        if cmd_id is None:
            return None
        response = self.events.wait_for_event(EVENT_BLE_PAIRING_ENABLED, timeout=2.0)
        if isinstance(response, EventBlePairingEnabled):
            return response.pin_code
        return None

    def get_peers(self) -> Optional[List[dict]]:
        """Compatibility alias for BLE peer list API."""
        return self.get_ble_peers()

    def disable_ble_pairing(self) -> bool:
        """Disable BLE pairing."""
        cmd_id = self.commands.ble_disable_pairing()
        if cmd_id is None:
            return False
        response = self.events.wait_for_response(cmd_id)
        return isinstance(response, EventCmdAck) and response.status == 0

    def get_ble_peers(self) -> Optional[List[dict]]:
        """Get BLE peer list."""
        cmd_id = self.commands.ble_get_peers()
        if cmd_id is None:
            return None
        response = self.events.wait_for_event(EVENT_BLE_PEERS_LIST, timeout=2.0)
        if isinstance(response, EventBlePeersList):
            return [{'mac': mac, 'rssi': rssi} for mac, rssi in response.peers]
        return None

    def start_ble_scan(self, interval_s: int = 5) -> bool:
        """Start BLE RSSI scan."""
        cmd_id = self.commands.ble_start_scan(interval_s)
        if cmd_id is None:
            return False
        response = self.events.wait_for_response(cmd_id)
        return isinstance(response, EventCmdAck) and response.status == 0

    # System operations
    def ping(self) -> bool:
        """Send ping and wait for response."""
        cmd_id = self.commands.ping()
        if cmd_id is None:
            return False
        response = self.events.wait_for_response(cmd_id, timeout=2.0)
        return isinstance(response, EventCmdAck) and response.status == 0

    def heartbeat(self) -> Optional[int]:
        """Send heartbeat and get connection state."""
        cmd_id = self.commands.heartbeat()
        if cmd_id is None:
            return None
        response = self.events.wait_for_event(EVENT_HEARTBEAT, timeout=2.0)
        if isinstance(response, EventHeartbeat):
            return response.connection_state
        return None

    def request_sync(self) -> Optional[int]:
        """Send a sync request and wait for a sync response."""
        cmd_id = self.commands.sync_request()
        if cmd_id is None:
            return None
        response = self.events.wait_for_event(EVENT_SYNC_RESPONSE, timeout=5.0)
        if isinstance(response, EventSyncResponse):
            return response.session_version
        return None

    def confirm_sync(self, correlation_id: int, stage: int = 0) -> bool:
        """Confirm a received ACK or result with CMD_SYN."""
        cmd_id = self.commands.sync_confirm(correlation_id, stage)
        if cmd_id is None:
            return False
        response = self.events.wait_for_response(cmd_id, timeout=2.0)
        return isinstance(response, EventCmdAck) and response.status == 0
