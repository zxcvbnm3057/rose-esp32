"""System endpoints: device status, ping, heartbeat, sync, thread."""
import base64
import time
from fastapi import APIRouter, HTTPException
from ..config import get_capabilities
from ..services import bridge_service
from ..models.schemas import ApiResponse, SyncConfirmRequest, ThreadPassthroughRequest
from .errors import check_connected, check_bridge_ok

router = APIRouter(tags=["system"])


@router.get("/device/status")
async def get_device_status():
    connected = bridge_service.is_connected()
    return ApiResponse(success=True, data={
        "connected": connected,
        "io_snapshot": {"gpios": [], "uarts": [], "ble": {"pairing_enabled": False, "scan_enabled": False, "peer_count": 0}},
    }, timestamp=time.time())


@router.post("/system/ping")
async def system_ping():
    check_connected()
    ok = await bridge_service.ping()
    check_bridge_ok(ok, "Ping failed")
    return ApiResponse(success=True, data={"pong": ok}, timestamp=time.time())


@router.post("/system/heartbeat")
async def system_heartbeat():
    check_connected()
    state = await bridge_service.heartbeat()
    check_bridge_ok(state, "Heartbeat failed")
    return ApiResponse(success=True, data={"connection_state": state}, timestamp=time.time())


@router.post("/system/sync")
async def system_sync():
    check_connected()
    session = await bridge_service.sync_request()
    check_bridge_ok(session, "Sync request failed")
    return ApiResponse(success=True, data={"session_version": session}, timestamp=time.time())


@router.post("/system/sync/confirm")
async def system_sync_confirm(req: SyncConfirmRequest = None):
    check_connected()
    ok = await bridge_service.sync_confirm(req.correlation_id, req.stage)
    check_bridge_ok(ok, "Sync confirm failed")
    return ApiResponse(success=True, data={"correlation_id": req.correlation_id}, timestamp=time.time())


@router.post("/thread/passthrough")
async def thread_passthrough(req: ThreadPassthroughRequest = None):
    if not get_capabilities().get("thread", False):
        raise HTTPException(status_code=501, detail="Thread not supported on this hardware")
    check_connected()
    try:
        payload_bytes = base64.b64decode(req.payload)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 payload")
    ok = await bridge_service.thread_passthrough(req.device_id, payload_bytes, req.correlation_id)
    check_bridge_ok(ok, "Thread passthrough failed")
    return ApiResponse(success=True, data={"device_id": req.device_id}, timestamp=time.time())
