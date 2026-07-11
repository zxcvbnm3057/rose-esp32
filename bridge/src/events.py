"""
Event handler for IoT Agent.

This module provides classes for handling and parsing events received
from the ESP32 IoT Agent.
"""

import logging
import threading
import time
from typing import Dict, Any, Optional, Callable, List
from .protocol import *

logger = logging.getLogger(__name__)


class EventHandler:
    """Handler for processing events from IoT Agent."""

    def __init__(self) -> None:
        self.event_callbacks: Dict[int, List[Callable[[Any], None]]] = {}
        self.pending_responses: Dict[int, List[Any]] = {}
        self.pending_events: Dict[int, List[Any]] = {}
        self._lock = threading.Lock()

    def register_callback(self, event_type: int, callback: Callable[[Any], None]) -> None:
        """Add callback for specific event type (multiple callbacks allowed)."""
        self.event_callbacks.setdefault(event_type, []).append(callback)

    def clear_pending(self) -> None:
        """Clear pending response and event queues."""
        with self._lock:
            self.pending_responses.clear()
            self.pending_events.clear()

    def handle_event(self, frame: MessageFrame) -> None:
        """Handle incoming event frame."""
        logger.debug(
            f"EventHandler got frame type={frame.msg_type}, cmd_id={frame.cmd_id}, length={frame.length}, payload={frame.payload.hex()}"
        )
        try:
            event = self._parse_event(frame)
            if event:
                opcode = frame.payload[0]
                # Index every event by opcode for opcode-based waits.
                with self._lock:
                    self.pending_events.setdefault(opcode, []).append(event)

                # Correlate command responses ONLY by the real command id carried
                # in the ACK payload. The frame-level `frame.cmd_id` is a device-
                # side event counter (see firmware send_event: cmd_id = cmd_counter++)
                # that is unrelated to the host's command id, so indexing responses
                # by it lets unrelated events (e.g. EVENT_BLE_PAIRING_DISABLED that
                # precedes the ACK) collide into pending_responses[real_cmd_id] and
                # be popped first by wait_for_response — surfacing as a spurious 502.
                if hasattr(event, 'cmd_id'):
                    with self._lock:
                        self.pending_responses.setdefault(event.cmd_id, []).append(event)

                # Call all registered callbacks (internal + user-registered)
                for cb in self.event_callbacks.get(opcode, []):
                    try:
                        cb(event)
                    except Exception:
                        logger.exception(f"Callback error for event {opcode}")

        except Exception as e:
            logger.error(f"Error handling event: {e}")

    def wait_for_response(self, cmd_id: int, timeout: float = 5.0) -> Optional[Any]:
        """Wait for response to a command."""
        import time
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self._lock:
                responses = self.pending_responses.get(cmd_id)
                if responses:
                    response = responses.pop(0)
                    if not responses:
                        self.pending_responses.pop(cmd_id, None)
                    return response
            time.sleep(0.01)
        return None

    def wait_for_event(self, event_type: int, timeout: float = 5.0) -> Optional[Any]:
        """Wait for event by opcode in FIFO order."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self._lock:
                events = self.pending_events.get(event_type)
                if events:
                    event = events.pop(0)
                    if not events:
                        self.pending_events.pop(event_type, None)
                    return event
            time.sleep(0.01)
        return None

    def wait_for_response_of_type(self, cmd_id: int, types: tuple, timeout: float = 5.0) -> Optional[Any]:
        """Wait for a response correlated by cmd_id whose type is in ``types``.

        A single command can produce several responses sharing the same cmd_id
        (e.g. CMD_SYNC_REQUEST emits EVENT_CMD_ACK *then* EVENT_SYNC_RESPONSE).
        FIFO ``wait_for_response`` would pop the ACK first and mis-handle the
        real result. This scans pending_responses[cmd_id] for the first entry
        matching the requested type(s), removing it and leaving the rest intact.
        ``EventError`` is always matched so failures surface immediately.
        """
        from .protocol import EventError
        match = types + (EventError,)
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self._lock:
                responses = self.pending_responses.get(cmd_id)
                if responses:
                    for i, resp in enumerate(responses):
                        if isinstance(resp, match):
                            matched = responses.pop(i)
                            if not responses:
                                self.pending_responses.pop(cmd_id, None)
                            return matched
            time.sleep(0.01)
        return None

    def wait_for_event_matching(self,
                                event_type: int,
                                predicate: Callable[[Any], bool],
                                timeout: float = 5.0) -> Optional[Any]:
        """Wait for first event by opcode that matches predicate."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self._lock:
                events = self.pending_events.get(event_type)
                if events:
                    for i, event in enumerate(events):
                        if predicate(event):
                            matched = events.pop(i)
                            if not events:
                                self.pending_events.pop(event_type, None)
                            return matched
            time.sleep(0.01)
        return None

    def wait_for_capture_or_error(self,
                                  event_type: int,
                                  cmd_id: int,
                                  predicate: Callable[[Any], bool],
                                  timeout: float = 5.0) -> Any:
        """Wait for the capture result or device error for a specific command.

        Both EVENT_GPIO_SIGNAL_CAPTURED and EventError now carry the originating
        cmd_id in their payload, so both are indexed in pending_responses[cmd_id]
        (see handle_event). Correlating by cmd_id — rather than by opcode — means
        a stale/late capture from a previous command can never be mistaken for
        this command's result. Returns the captured event or the EventError, or
        None on timeout. ``event_type``/``predicate`` are kept for API symmetry.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self._lock:
                responses = self.pending_responses.get(cmd_id)
                if responses:
                    response = responses.pop(0)
                    if not responses:
                        self.pending_responses.pop(cmd_id, None)
                    return response
            time.sleep(0.01)
        return None

    def discard_events_matching(self,
                                event_type: int,
                                predicate: Callable[[Any], bool]) -> int:
        """Remove queued events of a specific opcode that match predicate.

        Returns the number of discarded events.
        """
        removed = 0
        with self._lock:
            events = self.pending_events.get(event_type)
            if not events:
                return 0
            kept = []
            for event in events:
                if predicate(event):
                    removed += 1
                else:
                    kept.append(event)
            if kept:
                self.pending_events[event_type] = kept
            else:
                self.pending_events.pop(event_type, None)
        return removed

    def _parse_event(self, frame: MessageFrame) -> Optional[Any]:
        """Parse event from message frame."""
        if len(frame.payload) < 1:
            return None

        opcode = frame.payload[0]
        data = frame.payload[1:]

        try:
            if opcode == EVENT_CMD_ACK:
                return EventCmdAck.from_bytes(data)
            elif opcode == EVENT_GPIO_VALUE:
                return EventGpioValue.from_bytes(data)
            elif opcode == EVENT_GPIO_EDGE:
                return EventGpioEdge.from_bytes(data)
            elif opcode == EVENT_ADC_VALUE:
                return EventAdcValue.from_bytes(data)
            elif opcode == EVENT_GPIO_SIGNAL_CAPTURED:
                return EventGpioSignalCaptured.from_bytes(data)
            elif opcode == EVENT_UART_RX:
                return EventUartRx.from_bytes(data)
            elif opcode == EVENT_THREAD_RESPONSE:
                return EventThreadResponse.from_bytes(data)
            elif opcode == EVENT_SYNC_RESPONSE:
                return EventSyncResponse.from_bytes(data)
            elif opcode == EVENT_PORT_STATUS:
                return EventPortStatus.from_bytes(data)
            elif opcode == EVENT_BLE_PAIRING_ENABLED:
                return EventBlePairingEnabled.from_bytes(data)
            elif opcode == EVENT_BLE_PAIRING_DISABLED:
                return EventBlePairingDisabled.from_bytes(data)
            elif opcode == EVENT_BLE_IN_RANGE_LIST:
                return EventBleInRangeList.from_bytes(data)
            elif opcode == EVENT_BLE_DEVICE_IN_RANGE:
                return EventBleDeviceInRange.from_bytes(data)
            elif opcode == EVENT_BLE_DEVICE_OUT_OF_RANGE:
                return EventBleDeviceOutOfRange.from_bytes(data)
            elif opcode == EVENT_BLE_RSSI:
                return EventBleRssi.from_bytes(data)
            elif opcode == EVENT_HEARTBEAT:
                return EventHeartbeat.from_bytes(data)
            elif opcode == EVENT_UART_STATUS:
                return EventUartStatus.from_bytes(data)
            elif opcode == EVENT_GPIO_STATUS:
                return EventGpioStatus.from_bytes(data)
            elif opcode == EVENT_BLE_STATUS:
                return EventBleStatus.from_bytes(data)
            elif opcode == EVENT_ERROR:
                return EventError.from_bytes(data)
            else:
                logger.warning(f"Unknown event opcode: {opcode}")
                return None
        except Exception as e:
            logger.error(f"Error parsing event {opcode}: {e}")
            return None
