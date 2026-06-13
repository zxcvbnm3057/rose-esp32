"""UART endpoints."""
import base64
import time
from fastapi import APIRouter, Path, Query, HTTPException
from ..config import get_capabilities
from ..services import bridge_service
from ..models.schemas import ApiResponse, UartConfigRequest, UartSendRequest
from .errors import check_connected, check_bridge_ok

router = APIRouter(prefix="/uart", tags=["uart"])


@router.post("/{uart_id}/config")
async def uart_config(uart_id: int = Path(...), req: UartConfigRequest = None):
    if not get_capabilities().get("uart", False):
        raise HTTPException(status_code=501, detail="uart not supported")
    check_connected()

    ok = await bridge_service.uart_config(uart_id, req.baudrate, req.tx_gpio, req.rx_gpio,
                                          req.data_bits, req.parity, req.stop_bits)
    check_bridge_ok(ok, "UART config failed")
    return ApiResponse(success=True, data={"uart_id": uart_id, "baudrate": req.baudrate}, timestamp=time.time())


@router.post("/{uart_id}/send")
async def uart_send(uart_id: int = Path(...), req: UartSendRequest = None):
    if not get_capabilities().get("uart", False):
        raise HTTPException(status_code=501, detail="uart not supported")
    check_connected()

    if req.data_base64:
        data = base64.b64decode(req.data_base64)
    elif req.data:
        data = req.data.encode(req.encoding)
    else:
        raise HTTPException(status_code=400, detail="No data provided")

    ok = await bridge_service.uart_send(uart_id, data)
    check_bridge_ok(ok, "UART send failed")
    return ApiResponse(success=True, data={"uart_id": uart_id, "bytes_sent": len(data)}, timestamp=time.time())


@router.get("/{uart_id}/read")
async def uart_read(
    uart_id: int = Path(...),
    length: int = Query(default=256, ge=1, le=4096),
):
    if not get_capabilities().get("uart", False):
        raise HTTPException(status_code=501, detail="uart not supported")
    check_connected()

    result = await bridge_service.uart_read(uart_id, length)
    check_bridge_ok(result, "UART read failed — no data")
    return ApiResponse(success=True, data={
        "uart_id": uart_id,
        "data_base64": base64.b64encode(result).decode(),
        "length": len(result),
    }, timestamp=time.time())
