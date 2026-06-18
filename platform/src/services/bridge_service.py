"""Bridge client singleton — wraps IoTAgentClient from the bridge module."""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Optional, Any, Callable
from concurrent.futures import ThreadPoolExecutor

from ..bridge.client import IoTAgentClient

logger = logging.getLogger(__name__)

def _format_mac(raw: bytes) -> str:
    """Reverse BLE little-endian MAC bytes → XX:XX:XX:XX:XX:XX."""
    if not raw or len(raw) < 6:
        return ""
    return ":".join(f"{b:02x}" for b in reversed(raw[:6]))

# Global singleton
_client: Optional[IoTAgentClient] = None
_executor = ThreadPoolExecutor(max_workers=4)
_event_callback: Optional[Callable[[dict], None]] = None

def get_client() -> IoTAgentClient:
    global _client
    if _client is None:
        _client = IoTAgentClient(host="0.0.0.0", port=8080)
    return _client


def set_event_callback(cb: Callable[[dict], None]):
    global _event_callback
    _event_callback = cb


def _bridge_event_handler(event: Any):
    """Called from bridge event thread — forward to async callback."""
    if _event_callback:
        try:
            _event_callback(event)
        except Exception:
            logger.exception("Error in event callback")


async def start_bridge():
    """Start the bridge server (TCP listener) in a background thread."""
    client = get_client()

    # Register WS broadcast callbacks on the client's OWN event handler
    # (do NOT replace client.server.event_callback — the client needs it for ACK correlation)
    from ..bridge.protocol import (
        EVENT_GPIO_VALUE, EVENT_GPIO_EDGE, EVENT_ADC_VALUE,
        EVENT_GPIO_SIGNAL_CAPTURED, EVENT_UART_RX,
        EVENT_UART_STATUS, EVENT_GPIO_STATUS, EVENT_BLE_STATUS,
        EVENT_PORT_STATUS, EVENT_BLE_PAIRING_ENABLED, EVENT_BLE_PAIRING_DISABLED,
        EVENT_BLE_PEER_CONNECTED, EVENT_BLE_PEER_DISCONNECTED,
        EVENT_BLE_PEERS_LIST, EVENT_BLE_RSSI,
        EVENT_HEARTBEAT, EVENT_ERROR, EVENT_CMD_ACK, EVENT_SYNC_RESPONSE,
    )

    def make_callback(event_type: str):
        def cb(event: Any):
            data = _event_to_dict(event_type, event)
            if _event_callback and data:
                _event_callback({"type": event_type, **data})
        return cb

    handler = client.events  # use the client's own handler
    handler.register_callback(EVENT_GPIO_VALUE, make_callback("gpio_value"))
    handler.register_callback(EVENT_GPIO_EDGE, make_callback("gpio_edge"))
    handler.register_callback(EVENT_ADC_VALUE, make_callback("adc_value"))
    handler.register_callback(EVENT_GPIO_SIGNAL_CAPTURED, make_callback("signal_captured"))
    handler.register_callback(EVENT_UART_RX, make_callback("uart_rx"))
    handler.register_callback(EVENT_UART_STATUS, make_callback("uart_status"))
    handler.register_callback(EVENT_GPIO_STATUS, make_callback("gpio_status"))
    handler.register_callback(EVENT_BLE_STATUS, make_callback("ble_status"))
    handler.register_callback(EVENT_PORT_STATUS, make_callback("port_status"))
    handler.register_callback(EVENT_BLE_PAIRING_ENABLED, make_callback("ble_pairing_enabled"))
    handler.register_callback(EVENT_BLE_PAIRING_DISABLED, make_callback("ble_pairing_disabled"))
    handler.register_callback(EVENT_BLE_PEER_CONNECTED, make_callback("ble_peer_connected"))
    handler.register_callback(EVENT_BLE_PEER_DISCONNECTED, make_callback("ble_peer_disconnected"))
    handler.register_callback(EVENT_BLE_PEERS_LIST, make_callback("ble_peers_list"))
    handler.register_callback(EVENT_BLE_RSSI, make_callback("ble_rssi"))
    handler.register_callback(EVENT_HEARTBEAT, make_callback("heartbeat"))
    handler.register_callback(EVENT_ERROR, make_callback("error"))
    handler.register_callback(EVENT_CMD_ACK, make_callback("cmd_ack"))
    handler.register_callback(EVENT_SYNC_RESPONSE, make_callback("sync_response"))

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, client.start)
    logger.info("Bridge started")


def _mac_rev(mac: bytes) -> str:
    """Reverse BLE little-endian MAC bytes to colon-separated display format."""
    return _format_mac(mac)


def _event_to_dict(event_type: str, event: Any) -> Optional[dict]:
    """Convert a bridge event object to a plain dict."""
    try:
        if event_type == "gpio_value":
            return {"gpio": event.gpio, "value": event.value, "timestamp_us": event.timestamp_us}
        if event_type == "gpio_edge":
            return {"gpio": event.gpio, "edge_type": event.edge_type, "timestamp_us": event.timestamp_us}
        if event_type == "adc_value":
            return {"gpio": event.gpio, "value": event.value, "timestamp_us": event.timestamp_us}
        if event_type == "signal_captured":
            edges = [{"level": e.level, "duration_us": e.duration_us} for e in (event.edges or [])]
            return {"gpio": event.gpio, "edge_count": event.edge_count, "edges": edges, "timestamp_us": event.timestamp_us}
        if event_type == "uart_rx":
            import base64
            return {"uart_id": event.uart_id, "data_base64": base64.b64encode(event.data).decode()}
        if event_type == "port_status":
            return {"resource_type": event.resource_type, "id": event.id, "in_use": event.in_use, "mode": getattr(event, "mode", None), "value": getattr(event, "value", None)}
        if event_type == "ble_pairing_enabled":
            return {"pin_code": getattr(event, "pin_code", b"").decode() if hasattr(event, "pin_code") else "", "timeout_s": getattr(event, "timeout_s", 0)}
        if event_type == "ble_pairing_disabled":
            return {"reason": getattr(event, "reason", 0)}
        if event_type == "ble_peer_connected":
            return {"mac": _mac_rev(getattr(event, "peer_mac", b"")), "rssi": getattr(event, "rssi", 0)}
        if event_type == "ble_peer_disconnected":
            return {"mac": _mac_rev(getattr(event, "peer_mac", b"")), "reason": getattr(event, "reason", 0)}
        if event_type == "ble_peers_list":
            peers = [{"mac": _mac_rev(mac) if isinstance(mac, bytes) else str(mac), "rssi": rssi} for mac, rssi in (getattr(event, "peers", []) or [])]
            return {"peers": peers, "peer_count": len(peers)}
        if event_type == "ble_rssi":
            return {"mac": _mac_rev(getattr(event, "peer_mac", b"")), "rssi": getattr(event, "rssi", 0)}
        if event_type == "heartbeat":
            return {"connection_state": getattr(event, "connection_state", 0)}
        if event_type == "error":
            return {"error_code": getattr(event, "error_code", 0), "message": getattr(event, "message", "")}
        if event_type == "cmd_ack":
            return {"cmd_id": event.cmd_id, "status": event.status, "error_code": getattr(event, "error_code", 0)}
        if event_type == "sync_response":
            return {"session_version": event.session_version, "port_status_count": getattr(event, "port_status_count", 0)}
        if event_type == "uart_status":
            return {
                "uart_id": event.uart_id, "baudrate": event.baudrate,
                "data_bits": event.data_bits, "parity": event.parity, "stop_bits": event.stop_bits,
                "tx_gpio": event.tx_gpio, "rx_gpio": event.rx_gpio,
                "in_use": event.in_use, "owner": event.owner,
            }
        if event_type == "gpio_status":
            return {
                "gpio": event.gpio, "mode": event.mode, "pull": event.pull, "edge": event.edge,
                "value": event.value, "in_use": event.in_use, "owner": event.owner,
                "adc_raw": event.adc_raw, "adc_mv": event.adc_mv,
            }
        if event_type == "ble_status":
            return {
                "pairing_enabled": event.pairing_enabled,
                "scan_enabled": event.scan_enabled,
                "peer_count": event.peer_count,
                "pairing_timeout_s": event.pairing_timeout_s,
            }
    except Exception:
        logger.exception(f"Error converting event {event_type}")
    return None


async def stop_bridge():
    """Stop the bridge."""
    client = get_client()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, client.stop)
    logger.info("Bridge stopped")


def is_connected() -> bool:
    return get_client().is_connected()


def get_last_error() -> Optional[int]:
    """Return the firmware error code (IOT_ERR_*) from the last failed command.

    None means "unknown" (e.g. timeout / no response). Set by the bridge
    client whenever an ACK-based command fails; lets the API surface a
    precise reason instead of a generic message.
    """
    return getattr(get_client(), "last_error", None)


def _run_sync(func, *args, **kwargs):
    """Run a synchronous bridge method in thread pool."""
    return asyncio.get_running_loop().run_in_executor(_executor, func, *args, **kwargs)


# ── Convenient async wrappers ──────────────────────────────────

async def gpio_config(gpio: int, mode: int, pull: int = 0, edge: int = 0) -> bool:
    return await _run_sync(get_client().configure_gpio, gpio, mode, pull, edge)


async def gpio_set(gpio: int, value: int) -> bool:
    return await _run_sync(get_client().set_gpio, gpio, value)


async def gpio_get(gpio: int) -> Optional[int]:
    return await _run_sync(get_client().get_gpio, gpio)


async def adc_sample(gpio: int, samples: int = 1) -> Optional[int]:
    return await _run_sync(get_client().read_adc, gpio, samples)


async def signal_tx(
    gpio: int,
    signal: list,
    delay_us: int = 0,
    carrier_hz: int = 0,
    duty_cycle: float = 0.5,
) -> bool:
    tx = [(s["level"], s["duration_us"]) for s in signal]
    return await _run_sync(get_client().send_signal, gpio, tx, delay_us, carrier_hz, duty_cycle)


async def signal_rx(gpio: int, timeout_us: int, max_edges: int,
                    resolution: "int | str | None" = None) -> Optional[list]:
    # resolution (preset name / int us / None) is applied as a software
    # glitch-merge in the bridge client; firmware always captures at finest.
    return await _run_sync(get_client().receive_signal, gpio, timeout_us, max_edges, resolution)


async def signal_exchange(gpio: int, tx_signal: list, delay_us: int,
                          rx_total_us: int, rx_max_edges: int,
                          carrier_hz: int = 0,
                          duty_cycle: float = 0.5,
                          resolution: "int | str | None" = None) -> Optional[list]:
    # Firmware captures at finest resolution; the bridge client applies the
    # requested resolution (preset name or microseconds) in software via
    # glitch-merging.  No clamp here — the client normalizes the value.
    tx = [(s["level"], s["duration_us"]) for s in tx_signal]
    return await _run_sync(get_client().exchange_signals,
                           gpio, tx, delay_us, carrier_hz, duty_cycle, rx_total_us, rx_max_edges, resolution)


async def uart_config(uart_id: int, baudrate: int, tx_gpio: int, rx_gpio: int,
                      data_bits: int = 8, parity: int = 0, stop_bits: int = 1) -> bool:
    listener = await _run_sync(get_client().configure_uart, uart_id, baudrate, tx_gpio, rx_gpio,
                               data_bits, parity, stop_bits)
    return listener is not None


async def uart_send(uart_id: int, data: bytes) -> bool:
    return await _run_sync(get_client().send_uart, uart_id, data)


async def uart_read(uart_id: int, length: int = 256) -> Optional[bytes]:
    return await _run_sync(get_client().read_uart, uart_id, length)


async def port_bind(resource_type: int, id: int, owner_id: int = 0) -> bool:
    from ..bridge.protocol import EventCmdAck
    cmd_id = get_client().commands.port_bind(resource_type, id, owner_id)
    if cmd_id is None:
        return False
    # Wait briefly for ACK
    response = get_client().events.wait_for_response(cmd_id, timeout=3.0)
    return isinstance(response, EventCmdAck) and response.status == 0


async def port_unbind(resource_type: int, id: int) -> bool:
    from ..bridge.protocol import EventCmdAck
    cmd_id = get_client().commands.port_unbind(resource_type, id)
    if cmd_id is None:
        return False
    response = get_client().events.wait_for_response(cmd_id, timeout=3.0)
    return isinstance(response, EventCmdAck) and response.status == 0


async def port_status(resource_type: int, id: int) -> Optional[dict]:
    from ..bridge.protocol import EventPortStatus, EVENT_PORT_STATUS
    get_client().events.discard_events_matching(
        EVENT_PORT_STATUS,
        lambda event: isinstance(event, EventPortStatus)
        and event.resource_type == resource_type
        and event.id == id,
    )
    cmd_id = get_client().commands.port_status(resource_type, id)
    if cmd_id is None:
        return None
    response = get_client().events.wait_for_event_matching(
        EVENT_PORT_STATUS,
        lambda event: isinstance(event, EventPortStatus)
        and event.resource_type == resource_type
        and event.id == id,
        timeout=3.0,
    )
    if isinstance(response, EventPortStatus):
        return {
            "resource_type": response.resource_type,
            "id": response.id,
            "in_use": response.in_use,
            "mode": getattr(response, "mode", None),
            "pull": getattr(response, "pull", None),
            "edge": getattr(response, "edge", None),
            "value": getattr(response, "value", None),
            "owner": getattr(response, "owner", None),
            "adc_raw": getattr(response, "adc_raw", None),
            "adc_mv": getattr(response, "adc_mv", None),
        }
    return None


async def ble_enable_pairing(timeout_s: int = 60) -> Optional[str]:
    return await _run_sync(get_client().enable_ble_pairing, timeout_s)


async def ble_disable_pairing() -> bool:
    return await _run_sync(get_client().disable_ble_pairing)


async def ble_get_peers() -> Optional[list]:
    raw = await _run_sync(get_client().get_ble_peers)
    if not raw:
        return []
    result = []
    for item in raw:
        if isinstance(item, dict):
            mac = item.get("mac", b"")
            rssi = item.get("rssi", 0)
            if isinstance(mac, bytes):
                mac = _format_mac(mac)
            result.append({"mac": mac, "rssi": rssi})
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            mac, rssi = item
            if isinstance(mac, bytes):
                mac = _format_mac(mac)
            result.append({"mac": mac, "rssi": rssi})
        elif hasattr(item, 'mac') and hasattr(item, 'rssi'):
            mac = _format_mac(item.mac) if isinstance(item.mac, bytes) else str(item.mac)
            result.append({"mac": mac, "rssi": item.rssi})
    return result


async def ble_start_scan(interval_s: int = 5) -> bool:
    return await _run_sync(get_client().start_ble_scan, interval_s)


async def ble_stop_scan() -> bool:
    return await _run_sync(get_client().stop_ble_scan)


async def ping() -> bool:
    return await _run_sync(get_client().ping)


async def heartbeat() -> Optional[int]:
    return await _run_sync(get_client().heartbeat)


async def sync_request() -> Optional[int]:
    return await _run_sync(get_client().request_sync)


async def sync_confirm(correlation_id: int, stage: int = 0) -> bool:
    return await _run_sync(get_client().confirm_sync, correlation_id, stage)


async def thread_passthrough(device_id: int, payload_bytes: bytes, correlation_id: int = 0) -> bool:
    from ..bridge.protocol import EventCmdAck
    cmd_id = get_client().commands.thread_passthrough(device_id, payload_bytes, correlation_id)
    if cmd_id is None:
        return False
    response = get_client().events.wait_for_response(cmd_id, timeout=5.0)
    return isinstance(response, EventCmdAck) and response.status == 0
