"""GPIO endpoints."""
import asyncio
import time
from fastapi import APIRouter, Path, HTTPException
from ..config import get_capabilities, get_pins
from ..services import bridge_service
from ..ws.manager import manager
from ..models.schemas import (
    ApiResponse, GpioConfigRequest, GpioSetRequest, AdcSampleRequest,
)
from .errors import check_connected, check_bridge_ok

router = APIRouter(prefix="/gpio", tags=["gpio"])


def _check_capability(cap: str):
    caps = get_capabilities()
    if not caps.get(cap, False):
        raise HTTPException(status_code=501, detail=f"{cap} not supported on this hardware")


def _find_pin(gpio: int) -> dict:
    pins = get_pins()
    for p in pins:
        if p["gpio"] == gpio:
            return p
    raise HTTPException(status_code=404, detail=f"GPIO {gpio} not found in hardware config")


def _check_not_reserved(pin: dict):
    if pin.get("reserved"):
        raise HTTPException(status_code=403, detail=f"GPIO {pin['gpio']} is reserved ({pin.get('reserved_reason', 'unknown')})")


@router.post("/{gpio}/config")
async def gpio_config(gpio: int = Path(...), req: GpioConfigRequest = None):
    _check_capability("gpio")
    pin = _find_pin(gpio)
    _check_not_reserved(pin)
    check_connected()

    ok = await bridge_service.gpio_config(gpio, req.mode, req.pull, req.edge)
    check_bridge_ok(ok, "GPIO config failed")
    return ApiResponse(success=True, data={"gpio": gpio, "mode": req.mode}, timestamp=time.time())


@router.post("/{gpio}/set")
async def gpio_set(gpio: int = Path(...), req: GpioSetRequest = None):
    _check_capability("gpio")
    check_connected()

    ok = await bridge_service.gpio_set(gpio, req.value)
    check_bridge_ok(ok, "GPIO set failed")

    # Broadcast value change to WebSocket clients
    await manager.broadcast({
        "type": "gpio_value", "gpio": gpio, "value": req.value,
        "timestamp_us": int(time.time() * 1_000_000),
    })

    return ApiResponse(success=True, data={"gpio": gpio, "value": req.value}, timestamp=time.time())


@router.get("/{gpio}/get")
async def gpio_get(gpio: int = Path(...)):
    _check_capability("gpio")
    check_connected()

    value = await bridge_service.gpio_get(gpio)
    check_bridge_ok(value, "GPIO read failed")
    return ApiResponse(success=True, data={"gpio": gpio, "value": value}, timestamp=time.time())


@router.post("/{gpio}/adc")
async def gpio_adc(gpio: int = Path(...), req: AdcSampleRequest = None):
    _check_capability("adc")
    check_connected()

    value = await bridge_service.adc_sample(gpio, req.samples)
    check_bridge_ok(value, "ADC read failed")
    return ApiResponse(success=True, data={
        "gpio": gpio, "value": value,
        "voltage_mv": round(value / 4095 * 3300, 1),
    }, timestamp=time.time())
