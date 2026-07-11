"""BLE endpoints."""
import time
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from ..config import get_capabilities
from ..services import bridge_service
from ..models.schemas import ApiResponse, BlePairingEnableRequest, BleScanStartRequest
from ..models.custom_cmd import BleDeviceName
from ..db.database import async_session
from sqlalchemy import select
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


@router.delete("/paired-devices/{mac:path}")
async def delete_ble_paired_device(mac: str):
    """Delete a BLE bond from firmware and its display name from the database."""
    if not get_capabilities().get("ble", False):
        raise HTTPException(status_code=501, detail="BLE not supported")
    check_connected()
    try:
        device_mac = bytes.fromhex(mac.replace(":", "").replace("-", ""))[::-1]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid BLE MAC address") from exc
    if len(device_mac) != 6:
        raise HTTPException(status_code=422, detail="Invalid BLE MAC address")

    ok = await bridge_service.ble_delete_bond(device_mac)
    check_bridge_ok(ok, "BLE bond deletion failed")
    async with async_session() as session:
        result = await session.execute(select(BleDeviceName).where(BleDeviceName.mac == mac))
        existing = result.scalar_one_or_none()
        if existing:
            await session.delete(existing)
            await session.commit()
    return ApiResponse(success=True, data={"mac": mac, "deleted": True}, timestamp=time.time())


@router.get("/in-range")
async def ble_get_in_range():
    if not get_capabilities().get("ble", False):
        raise HTTPException(status_code=501, detail="BLE not supported")
    check_connected()
    devices = await bridge_service.ble_get_in_range()
    check_bridge_ok(devices, "BLE in-range query failed")
    return ApiResponse(success=True, data={"devices": devices or []}, timestamp=time.time())


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


# ── BLE Device Name Mappings ──────────────────────────────────────

@router.get("/device-names")
async def list_ble_device_names():
    """List all BLE device name mappings."""
    async with async_session() as session:
        result = await session.execute(select(BleDeviceName))
        rows = result.scalars().all()
        return ApiResponse(success=True, data={
            "names": [{"mac": r.mac, "name": r.name} for r in rows]
        }, timestamp=time.time())


class BleDeviceNameRequest(BaseModel):
    name: str


@router.put("/device-names/{mac:path}")
async def set_ble_device_name(mac: str, req: BleDeviceNameRequest):
    """Set or update a BLE device display name for a MAC address."""
    from datetime import datetime
    async with async_session() as session:
        result = await session.execute(select(BleDeviceName).where(BleDeviceName.mac == mac))
        existing = result.scalar_one_or_none()
        if existing:
            existing.name = req.name
            existing.updated_at = datetime.utcnow()
        else:
            session.add(BleDeviceName(mac=mac, name=req.name, updated_at=datetime.utcnow()))
        await session.commit()
    return ApiResponse(success=True, data={"mac": mac, "name": req.name}, timestamp=time.time())


@router.delete("/device-names/{mac:path}")
async def delete_ble_device_name(mac: str):
    """Delete a BLE device name mapping."""
    async with async_session() as session:
        result = await session.execute(select(BleDeviceName).where(BleDeviceName.mac == mac))
        existing = result.scalar_one_or_none()
        if existing:
            await session.delete(existing)
            await session.commit()
    return ApiResponse(success=True, data={"mac": mac, "deleted": True}, timestamp=time.time())
