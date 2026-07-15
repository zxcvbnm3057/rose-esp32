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
from .protocol import EventCmdAck, EventGpioValue, EventAdcValue, EventGpioSignalCaptured, EventBlePairingEnabled, EventBleInRangeList, EventHeartbeat, EventUartRx, EventSyncResponse, EventError
from .protocol import EVENT_SYNC_RESPONSE, EVENT_GPIO_VALUE, EVENT_ADC_VALUE, EVENT_GPIO_SIGNAL_CAPTURED, EVENT_UART_RX, EVENT_HEARTBEAT, EVENT_BLE_IN_RANGE_LIST, EVENT_BLE_PAIRING_ENABLED, EVENT_ERROR, RESOURCE_GPIO, RESOURCE_UART

logger = logging.getLogger(__name__)


# ── Signal resolution (software glitch-merge) ────────────────────────────
#
# The firmware always captures GPIO signals at the finest resolution
# (RMT input filter fixed at 1 tick = 1us; pure-RX uses GPIO ISR which has
# no filter at all).  "Resolution" is therefore applied here in software:
# a pulse narrower than `resolution_us` is treated as a glitch — it is
# dropped and its duration folded into the preceding edge, mirroring the
# semantics of a hardware glitch filter.

# Named resolution presets (microseconds).  `exact` means no merging.
RESOLUTION_PRESETS: Dict[str, int] = {
    "exact": 1,      # finest — keep every captured edge (>=1us)
    "fine": 5,       # drop sub-5us spikes
    "normal": 20,    # drop sub-20us noise (typical for slow logic)
    "coarse": 100,   # drop sub-100us — only keep wide pulses
}


def resolve_resolution_us(resolution: "int | str | None") -> int:
    """Normalize a resolution given as a preset name, an int (us), or None.

    Returns the resolution in microseconds (>=1).  None / unknown -> 1 (exact).
    """
    if resolution is None:
        return 1
    if isinstance(resolution, str):
        return RESOLUTION_PRESETS.get(resolution.strip().lower(), 1)
    try:
        return max(1, int(resolution))
    except (TypeError, ValueError):
        return 1


def apply_resolution(edges: List[Tuple[int, int]], resolution_us: int) -> List[Tuple[int, int]]:
    """Glitch-merge edges so no kept pulse is narrower than `resolution_us`.

    Semantics (matches a hardware glitch filter):
      - A pulse shorter than `resolution_us` is a glitch: it is removed and
        its duration is added to the previous kept edge (so total elapsed
        time is preserved).
      - If a glitch occurs before any edge is kept, its duration is carried
        forward onto the first kept edge.
      - Consecutive same-level edges produced by a merge are coalesced.

    `edges` is a list of (level, duration_us).  resolution_us <= 1 is a no-op.
    """
    if resolution_us <= 1 or not edges:
        return list(edges)

    merged: List[Tuple[int, int]] = []
    carry = 0  # duration of dropped glitches waiting to be folded forward
    for level, duration in edges:
        if duration < resolution_us:
            # Glitch: drop it but preserve elapsed time.
            if merged:
                plevel, pdur = merged[-1]
                merged[-1] = (plevel, pdur + duration)
            else:
                carry += duration
            continue
        # Wide enough to keep.
        duration += carry
        carry = 0
        if merged and merged[-1][0] == level:
            # Same level as previous kept edge -> coalesce.
            plevel, pdur = merged[-1]
            merged[-1] = (plevel, pdur + duration)
        else:
            merged.append((level, duration))

    # Any trailing carry (glitches at the very start with nothing kept yet)
    # is folded onto the first edge if one exists.
    if carry and merged:
        flevel, fdur = merged[0]
        merged[0] = (flevel, fdur + carry)
    return merged



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

        # Last command error code propagated from the device (firmware IOT_ERR_*).
        # Set whenever a command fails; None after a successful command.
        # Lets the platform surface a precise reason instead of a generic 502.
        self.last_error: Optional[int] = None

        # Connect event handler to server
        self.server.set_event_callback(self.events.handle_event)
        self.events.register_callback(EVENT_UART_RX, self._handle_uart_rx_event)

    def _check_ack(self, response: Any) -> bool:
        """Validate a command response and record the device error code.

        Returns True only for a successful EventCmdAck (status == 0).
        On failure, stores the firmware error code in ``self.last_error``:
        - EventCmdAck with status != 0 -> its ``error_code``
        - EventError -> its ``err_code``
        - None (timeout) / unexpected -> None (unknown)
        """
        if isinstance(response, EventCmdAck) and response.status == 0:
            self.last_error = None
            return True
        if isinstance(response, EventCmdAck):
            self.last_error = response.error_code
        elif isinstance(response, EventError):
            self.last_error = response.err_code
        else:
            self.last_error = None  # timeout / no response
        return False

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
            self.last_error = None
            return False
        response = self.events.wait_for_response(cmd_id)
        if self._check_ack(response):
            return True

        # Retry once by unbinding stale GPIO ownership/state on device.
        unbind_id = self.commands.port_unbind(RESOURCE_GPIO, gpio)
        if unbind_id is not None:
            self.events.wait_for_response(unbind_id, timeout=1.0)
        retry_cmd_id = self.commands.gpio_config(gpio, mode, pull, edge)
        if retry_cmd_id is None:
            return False
        retry_response = self.events.wait_for_response(retry_cmd_id)
        return self._check_ack(retry_response)

    def set_gpio(self, gpio: int, value: int) -> bool:
        """Set GPIO value and wait for ACK."""
        cmd_id = self.commands.gpio_set(gpio, value)
        if cmd_id is None:
            self.last_error = None
            return False
        response = self.events.wait_for_response(cmd_id)
        return self._check_ack(response)

    def get_gpio(self, gpio: int) -> Optional[int]:
        """Get GPIO value."""
        cmd_id = self.commands.gpio_get(gpio)
        if cmd_id is None:
            return None
        # Correlate by cmd_id: the value event echoes the originating command id,
        # so a concurrent read on another gpio can't be mistaken for this one.
        response = self.events.wait_for_response_of_type(cmd_id, (EventGpioValue,), timeout=2.0)
        if isinstance(response, EventGpioValue):
            return response.value
        return None

    def read_adc(self, gpio: int, samples: int = 1) -> Optional[int]:
        """Read ADC value."""
        cmd_id = self.commands.adc_sample(gpio, samples)
        if cmd_id is None:
            return None
        # Correlate by cmd_id (see get_gpio).
        response = self.events.wait_for_response_of_type(cmd_id, (EventAdcValue,), timeout=2.0)
        if isinstance(response, EventAdcValue):
            return response.value
        return None

    def send_signal(
        self,
        gpio: int,
        signal: List[Tuple[int, int]],
        delay_us: int = 0,
        carrier_hz: int = 0,
        duty_cycle: float = 0.5,
        repeat: int = 1,
        repeat_gap_us: int = 0,
    ) -> bool:
        """Send GPIO signal sequence."""
        cmd_id = self.commands.gpio_signal_tx(
            gpio, signal, delay_us, carrier_hz, duty_cycle, repeat, repeat_gap_us,
        )
        if cmd_id is None:
            self.last_error = None
            return False
        signal_duration_us = sum(duration_us for _, duration_us in signal)
        total_duration_s = (
            signal_duration_us * repeat + repeat_gap_us * max(0, repeat - 1)
        ) / 1_000_000
        response = self.events.wait_for_response(cmd_id, timeout=max(5.0, total_duration_s + 2.0))
        return self._check_ack(response)

    def receive_signal(self,
                       gpio: int,
                       timeout_us: int = 1000000,
                       max_edges: int = 100,
                       resolution: "int | str | None" = None) -> Optional[List[Tuple[int, int]]]:
        """Receive GPIO signal.

        Returns empty list [] when capture succeeded but no edges detected.
        Returns None only when the command itself failed (send error or timeout).
        The ESP32 sends EVENT_GPIO_SIGNAL_CAPTURED (with edge_count possibly 0)
        followed by EVENT_CMD_ACK.  We consume the capture event; the ACK is
        handled by registered callbacks.

        `resolution` selects the software glitch-merge granularity: a preset
        name ("exact"/"fine"/"normal"/"coarse"), an int in microseconds, or
        None (== "exact", keep every captured edge).  Pulses narrower than the
        resolution are merged into the previous edge (see `apply_resolution`).
        """
        cmd_id = self.commands.gpio_signal_rx(gpio, timeout_us, max_edges)
        if cmd_id is None:
            return None

        response = self.events.wait_for_event_matching(
            EVENT_GPIO_SIGNAL_CAPTURED,
            lambda e: isinstance(e, EventGpioSignalCaptured) and e.gpio == gpio,
            timeout=timeout_us / 1000000 + 2.0,
        )
        if isinstance(response, EventGpioSignalCaptured):
            edges = [(edge.level, edge.duration_us) for edge in (response.edges or [])]
            return apply_resolution(edges, resolve_resolution_us(resolution))
        return None

    def exchange_signals(self,
                         gpio: int,
                         tx_signal: List[Tuple[int, int]],
                         delay_us: int = 0,
                         carrier_hz: int = 0,
                         duty_cycle: float = 0.5,
                         rx_total_us: int = 1000000,
                         rx_max_edges: int = 100,
                         resolution: "int | str | None" = None) -> Optional[List[Tuple[int, int]]]:
        """Exchange signals (TX then RX).

        Returns empty list [] when exchange succeeded but no edges captured.
        Returns None only when the command itself failed (send error or timeout).
        The ESP32 sends EVENT_GPIO_SIGNAL_CAPTURED (with edge_count possibly 0)
        followed by EVENT_CMD_ACK.  We consume the capture event; the ACK is
        handled by registered callbacks.

        `resolution` selects the software glitch-merge granularity (preset name,
        int microseconds, or None == exact); see `receive_signal`.
        """
        cmd_id = self.commands.gpio_signal_exchange(
            gpio,
            tx_signal,
            delay_us,
            carrier_hz,
            duty_cycle,
            rx_total_us,
            rx_max_edges,
        )
        if cmd_id is None:
            return None

        # Success arrives as EVENT_GPIO_SIGNAL_CAPTURED (no cmd_id, matched by
        # opcode); failure arrives as an EventError correlated by cmd_id. Wait
        # for whichever comes first so a failed capture reports a real reason
        # (e.g. RESOURCE_EXHAUSTED) instead of a generic timeout.
        self.last_error = None
        response = self.events.wait_for_capture_or_error(
            EVENT_GPIO_SIGNAL_CAPTURED,
            cmd_id,
            lambda e: isinstance(e, EventGpioSignalCaptured) and e.gpio == gpio,
            timeout=rx_total_us / 1000000 + 2.0,
        )
        if isinstance(response, EventGpioSignalCaptured):
            edges = [(edge.level, edge.duration_us) for edge in (response.edges or [])]
            return apply_resolution(edges, resolve_resolution_us(resolution))
        if isinstance(response, EventError):
            self.last_error = response.err_code
        return None

    # UART operations
    def configure_uart(self, uart_id: int, baudrate: int, tx_gpio: int = 1, rx_gpio: int = 3,
                       data_bits: int = 8, parity: int = 0, stop_bits: int = 1) -> Optional[UartRxListener]:
        """Configure UART and return an RX listener queue on success."""
        cmd_id = self.commands.uart_config(uart_id, baudrate, data_bits, parity, stop_bits, tx_gpio, rx_gpio)
        if cmd_id is None:
            return None
        response = self.events.wait_for_response(cmd_id)
        if self._check_ack(response):
            listener = UartRxListener()
            self._uart_listeners[uart_id] = listener
            return listener

        # Retry once: unbind stale UART ownership then reconfigure
        unbind_id = self.commands.port_unbind(RESOURCE_UART, uart_id)
        if unbind_id is not None:
            self.events.wait_for_response(unbind_id, timeout=1.0)
        retry_cmd_id = self.commands.uart_config(uart_id, baudrate, data_bits, parity, stop_bits, tx_gpio, rx_gpio)
        if retry_cmd_id is None:
            return None
        retry_response = self.events.wait_for_response(retry_cmd_id)
        if self._check_ack(retry_response):
            listener = UartRxListener()
            self._uart_listeners[uart_id] = listener
            return listener
        return None

    def send_uart(self, uart_id: int, data: bytes) -> bool:
        """Send data via UART."""
        cmd_id = self.commands.uart_send(uart_id, data)
        if cmd_id is None:
            self.last_error = None
            return False
        response = self.events.wait_for_response(cmd_id)
        return self._check_ack(response)

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
        # Correlate by cmd_id (the pairing-enabled event echoes the command id).
        response = self.events.wait_for_response_of_type(cmd_id, (EventBlePairingEnabled,), timeout=2.0)
        if isinstance(response, EventBlePairingEnabled):
            return response.pin_code
        return None

    def get_in_range(self) -> Optional[List[dict]]:
        """Compatibility alias for BLE in-range device list API."""
        return self.get_ble_in_range()

    def disable_ble_pairing(self) -> bool:
        """Disable BLE pairing."""
        cmd_id = self.commands.ble_disable_pairing()
        if cmd_id is None:
            self.last_error = None
            return False
        response = self.events.wait_for_response(cmd_id)
        return self._check_ack(response)

    def get_ble_in_range(self) -> Optional[List[dict]]:
        """Get BLE in-range device list."""
        cmd_id = self.commands.ble_get_in_range()
        if cmd_id is None:
            return None
        # Correlate by cmd_id (the in-range list event echoes the command id).
        response = self.events.wait_for_response_of_type(cmd_id, (EventBleInRangeList,), timeout=2.0)
        if isinstance(response, EventBleInRangeList):
            return [{'mac': mac, 'rssi': rssi} for mac, rssi in response.devices]
        return None

    def start_ble_scan(self, interval_s: int = 5) -> bool:
        """Start BLE RSSI scan."""
        cmd_id = self.commands.ble_start_scan(interval_s)
        if cmd_id is None:
            self.last_error = None
            return False
        response = self.events.wait_for_response(cmd_id)
        return self._check_ack(response)

    def stop_ble_scan(self) -> bool:
        """Stop BLE RSSI scan."""
        cmd_id = self.commands.ble_stop_scan()
        if cmd_id is None:
            self.last_error = None
            return False
        response = self.events.wait_for_response(cmd_id)
        return self._check_ack(response)

    def delete_ble_bond(self, device_mac: bytes) -> bool:
        """Delete a bonded BLE peer from firmware storage."""
        cmd_id = self.commands.ble_delete_bond(device_mac)
        if cmd_id is None:
            self.last_error = None
            return False
        response = self.events.wait_for_response(cmd_id)
        return self._check_ack(response)

    # System operations
    def ping(self) -> bool:
        """Send ping and wait for response."""
        cmd_id = self.commands.ping()
        if cmd_id is None:
            self.last_error = None
            return False
        response = self.events.wait_for_response(cmd_id, timeout=2.0)
        return self._check_ack(response)

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
        # CMD_SYNC_REQUEST emits EVENT_CMD_ACK then EVENT_SYNC_RESPONSE (same
        # cmd_id); select the sync response by type so the ACK isn't mistaken.
        response = self.events.wait_for_response_of_type(cmd_id, (EventSyncResponse,), timeout=5.0)
        if isinstance(response, EventSyncResponse):
            return response.session_version
        return None

    def confirm_sync(self, correlation_id: int, stage: int = 0) -> bool:
        """Confirm a received ACK or result with CMD_SYN."""
        cmd_id = self.commands.sync_confirm(correlation_id, stage)
        if cmd_id is None:
            self.last_error = None
            return False
        response = self.events.wait_for_response(cmd_id, timeout=2.0)
        return self._check_ack(response)
