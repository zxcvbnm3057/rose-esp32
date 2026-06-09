"""FastAPI application entry point."""
from __future__ import annotations
import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException

from .api.router import api_router
from .api.custom_cmd import public_router as custom_cmd_public_router
from .ws.manager import manager
from .services import bridge_service
from .db.database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # Startup
    await init_db()
    logger.info("Database initialized")

    # Register bridge events → WebSocket broadcast
    bridge_service.set_event_callback(_on_bridge_event)

    # Start bridge TCP listener in background
    asyncio.create_task(_monitor_bridge())

    logger.info("Server ready")
    yield
    # Shutdown
    await bridge_service.stop_bridge()
    logger.info("Server stopped")


# Reference to the main event loop for cross-thread scheduling
_main_loop: asyncio.AbstractEventLoop | None = None


# ── GPIO state cache (populated by port_status / gpio_value events) ─────
# Survives across WS reconnects so new clients immediately see current state.
_gpio_state_cache: dict[int, dict] = {}
_uart_state_cache: dict[int, dict] = {}
_ble_state_cache: dict = {}


def _update_gpio_cache(gpio: int, update: dict):
    """Thread-safe update of the GPIO state cache."""
    entry = _gpio_state_cache.setdefault(gpio, {})
    entry.update(update)


def _on_bridge_event(event: dict):
    """Forward bridge events to all WebSocket clients (thread-safe).
    Also update the GPIO/UART state cache for new-client hydration."""
    loop = _main_loop
    if loop is not None:
        etype = event.get("type", "")
        if etype == "port_status" and event.get("resource_type") == 0:
            gpio = event["id"]
            update = {"bound": event.get("in_use") == 1}
            if "mode" in event:
                update["mode_code"] = event["mode"]
                modes = ["INPUT", "OUTPUT", "INTERRUPT", "ADC", "SIGNAL"]
                if 0 <= event["mode"] <= 4:
                    update["mode"] = modes[event["mode"]]
            if "value" in event:
                update["value"] = event["value"]
            _update_gpio_cache(gpio, update)
        elif etype == "gpio_status":
            gpio = event["gpio"]
            modes = ["INPUT", "OUTPUT", "INTERRUPT", "ADC", "SIGNAL"]
            pulls = ["NONE", "DOWN", "UP"]
            update = {
                "mode_code": event["mode"],
                "mode": modes[event["mode"]] if 0 <= event["mode"] <= 4 else "",
                "pull_code": event["pull"],
                "pull": pulls[event["pull"]] if 0 <= event["pull"] <= 2 else "",
                "edge": event["edge"],
                "value": event["value"],
                "bound": event["in_use"] == 1,
            }
            if event.get("adc_raw"):
                update["adc_value"] = event["adc_raw"]
                update["adc_voltage_mv"] = event["adc_mv"]
            _update_gpio_cache(gpio, update)
            # Also broadcast as gpio_status to WS
            ws_event = {"type": "gpio_status", **{k: v for k, v in event.items() if k != "type"}}
            asyncio.run_coroutine_threadsafe(manager.broadcast(ws_event), loop)
        elif etype == "uart_status":
            _uart_state_cache[event["uart_id"]] = {
                "uart_id": event["uart_id"],
                "bound": event["in_use"] == 1,
                "baudrate": event["baudrate"],
                "tx_gpio": event["tx_gpio"],
                "rx_gpio": event["rx_gpio"],
            }
            ws_event = {"type": "uart_status", **{k: v for k, v in event.items() if k != "type"}}
            asyncio.run_coroutine_threadsafe(manager.broadcast(ws_event), loop)
        elif etype == "ble_status":
            ws_event = {"type": "ble_status", **{k: v for k, v in event.items() if k != "type"}}
            asyncio.run_coroutine_threadsafe(manager.broadcast(ws_event), loop)
        elif etype in ("ble_pairing_enabled", "ble_pairing_disabled", "ble_peers_list",
                       "ble_peer_connected", "ble_peer_disconnected", "ble_rssi"):
            # 纯透传 — 设备是唯一真相源，后端不缓存
            ws_event = {"type": etype, **{k: v for k, v in event.items() if k != "type"}}
            asyncio.run_coroutine_threadsafe(manager.broadcast(ws_event), loop)
        elif etype == "gpio_value":
            gpio = event["gpio"]
            update = {"value": event["value"]}
            if "mode_code" in event:
                update["mode_code"] = event["mode_code"]
                update["mode"] = event.get("mode", "")
            if "pull_code" in event:
                update["pull_code"] = event["pull_code"]
            if "edge" in event:
                update["edge"] = event["edge"]
            _update_gpio_cache(gpio, update)

        asyncio.run_coroutine_threadsafe(manager.broadcast(event), loop)


async def _monitor_bridge():
    """Monitor bridge connection state and broadcast changes."""
    global _main_loop
    _main_loop = asyncio.get_running_loop()
    await bridge_service.start_bridge()
    was_connected = False
    while True:
        await asyncio.sleep(2)
        connected = bridge_service.is_connected()
        if connected != was_connected:
            was_connected = connected
            await manager.broadcast({"type": "connection_change", "connected": connected, "timestamp": time.time()})
            if connected:
                # Send hardware config
                from .config import load_hardware_config, get_pins
                await manager.broadcast({"type": "hardware_config", "data": load_hardware_config(), "timestamp": time.time()})
                # Spawn background sync — query all GPIO states and broadcast
                asyncio.create_task(_sync_device_state(0.5))


async def _sync_device_state(delay: float = 0.5):
    """Request full device state snapshot via CMD_SYNC_REQUEST + BLE peers."""
    if delay > 0:
        await asyncio.sleep(delay)
    try:
        await bridge_service.sync_request()
        # Device responds with EVENT_SYNC_RESPONSE + EVENT_PORT_STATUS × N
        # — broadcast to WS via _on_bridge_event → manager.broadcast()
    except Exception:
        pass
    # 同步 BLE 设备列表（设备是唯一真相源）
    try:
        await asyncio.sleep(0.5)
        await bridge_service.ble_get_peers()
        # — ESP32 返回 EVENT_BLE_PEERS_LIST → WS 透传
    except Exception:
        pass


app = FastAPI(
    title="Rose-ESP32 IoT Agent API",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins within LAN
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Error formatting ──────────────────────────────────────────
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Format all HTTPExceptions as ApiResponse JSON."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "data": None,
            "error": exc.detail,
            "timestamp": time.time(),
        },
    )


# Internal API
app.include_router(api_router)

# Public custom command URL (no /api/v1 prefix)
app.include_router(custom_cmd_public_router, prefix="/cmd", tags=["public_cmds"])


# ── WebSocket ─────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)

    # Send hardware config + current connection state on connect
    from .config import load_hardware_config
    from .db.database import async_session
    from .models.custom_cmd import PinLock, UartConfigModel
    from sqlalchemy import select

    await ws.send_json({"type": "hardware_config", "data": load_hardware_config(), "timestamp": time.time()})
    await ws.send_json({"type": "connection_change", "connected": bridge_service.is_connected(), "timestamp": time.time()})

    # Load expected states from DB (what the frontend last set)
    async with async_session() as session:
        # GPIO expected states
        result = await session.execute(select(PinLock))
        pin_locks = result.scalars().all()
        expected_gpios = []
        for r in pin_locks:
            expected_gpios.append({
                "gpio": r.gpio,
                "locked": bool(r.locked),
                "expected_mode": r.expected_mode,
                "expected_value": r.expected_value,
            })
        # UART expected states
        uart_result = await session.execute(select(UartConfigModel))
        uart_rows = uart_result.scalars().all()
        expected_uarts = []
        for r in uart_rows:
            expected_uarts.append({
                "uart_id": r.uart_id,
                "baudrate": r.baudrate,
                "tx_gpio": r.tx_gpio,
                "rx_gpio": r.rx_gpio,
            })
        if expected_gpios or expected_uarts:
            await ws.send_json({"type": "expected_state", "data": {
                "gpios": expected_gpios, "uarts": expected_uarts,
            }, "timestamp": time.time()})

    # Send cached GPIO state (actual, from chip via previous sync)
    if _gpio_state_cache:
        gpios = [{"gpio": k, **v} for k, v in _gpio_state_cache.items()]
        await ws.send_json({"type": "device_state", "data": {"gpios": gpios}, "timestamp": time.time()})

    # Trigger sync to refresh actual state from chip
    if bridge_service.is_connected():
        asyncio.create_task(_sync_device_state(0.3))

    try:
        while True:
            raw = await ws.receive_text()
            # Client can send commands via WS too
            import json
            try:
                msg = json.loads(raw)
                if msg.get("type") == "cmd":
                    await _handle_ws_command(ws, msg)
            except json.JSONDecodeError:
                pass
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await manager.disconnect(ws)


async def _handle_ws_command(ws: WebSocket, msg: dict):
    """Handle a command sent via WebSocket."""
    op = msg.get("op", "")
    try:
        if op == "gpio_set":
            ok = await bridge_service.gpio_set(msg["gpio"], msg["value"])
            await ws.send_json({"type": "cmd_result", "op": op, "success": ok, "data": {}})
        elif op == "gpio_get":
            val = await bridge_service.gpio_get(msg["gpio"])
            await ws.send_json({"type": "cmd_result", "op": op, "success": val is not None, "data": {"value": val}})
        elif op == "adc_sample":
            val = await bridge_service.adc_sample(msg["gpio"], msg.get("samples", 1))
            await ws.send_json({"type": "cmd_result", "op": op, "success": val is not None, "data": {"value": val}})
        else:
            await ws.send_json({"type": "cmd_result", "op": op, "success": False, "error": f"Unknown op: {op}"})
    except Exception as e:
        await ws.send_json({"type": "cmd_result", "op": op, "success": False, "error": str(e)})
