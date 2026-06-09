"""BLE endpoints."""
import time
from fastapi import APIRouter, HTTPException
from ..config import get_capabilities
from ..services import bridge_service
from ..models.schemas import ApiResponse, BlePairingEnableRequest, BleScanStartRequest
from .errors import check_connected, check_bridge_ok

router = APIRouter(prefix="/ble", tags=["ble"])


@router.post("/pairing/enable")
async def ble_enable_pairing(req: BlePairingEnableRequest = None):
    if not get_capabilities().get("ble", False):
        raise HTTPException(status_code=501, detail="BLE not supported")
    check_connected()
    pin = await bridge_service.ble_enable_pairing(req.timeout_s)
    check_bridge_ok(pin, "BLE pairing enable failed")
    return ApiResponse(success=True, data={"pin_code": pin, "timeout_s": req.timeout_s}, timestamp=time.time())


@router.post("/pairing/disable")
async def ble_disable_pairing():
    if not get_capabilities().get("ble", False):
        raise HTTPException(status_code=501, detail="BLE not supported")
    check_connected()
    ok = await bridge_service.ble_disable_pairing()
    check_bridge_ok(ok, "BLE pairing disable failed")
    return ApiResponse(success=True, data={"pairing_disabled": ok}, timestamp=time.time())


@router.get("/peers")
async def ble_get_peers():
    if not get_capabilities().get("ble", False):
        raise HTTPException(status_code=501, detail="BLE not supported")
    check_connected()
    peers = await bridge_service.ble_get_peers()
    check_bridge_ok(peers, "BLE peer query failed")
    return ApiResponse(success=True, data={"peers": peers or []}, timestamp=time.time())


@router.post("/scan/start")
async def ble_start_scan(req: BleScanStartRequest = None):
    if not get_capabilities().get("ble", False):
        raise HTTPException(status_code=501, detail="BLE not supported")
    check_connected()
    ok = await bridge_service.ble_start_scan(req.interval_s)
    check_bridge_ok(ok, "BLE scan start failed")
    return ApiResponse(success=True, data={"scan_started": ok}, timestamp=time.time())


@router.post("/scan/stop")
async def ble_stop_scan():
    if not get_capabilities().get("ble", False):
        raise HTTPException(status_code=501, detail="BLE not supported")
    check_connected()
    ok = await bridge_service.ble_stop_scan()
    check_bridge_ok(ok, "BLE scan stop failed")
    return ApiResponse(success=True, data={"scan_stopped": ok}, timestamp=time.time())
