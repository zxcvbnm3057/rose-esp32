"""Port bind/unbind/status endpoints."""
import time
from fastapi import APIRouter, Query
from ..services import bridge_service
from ..models.schemas import ApiResponse, PortBindRequest, PortUnbindRequest
from .errors import check_connected, check_bridge_ok

router = APIRouter(prefix="/port", tags=["port"])


@router.post("/bind")
async def port_bind(req: PortBindRequest = None):
    check_connected()
    ok = await bridge_service.port_bind(req.resource_type, req.id, req.owner_id)
    check_bridge_ok(ok, "Port bind failed")
    return ApiResponse(success=True, data={"resource_type": req.resource_type, "id": req.id}, timestamp=time.time())


@router.post("/unbind")
async def port_unbind(req: PortUnbindRequest = None):
    check_connected()
    ok = await bridge_service.port_unbind(req.resource_type, req.id)
    check_bridge_ok(ok, "Port unbind failed")
    return ApiResponse(success=True, data={"resource_type": req.resource_type, "id": req.id}, timestamp=time.time())


@router.get("/status")
async def port_status(resource_type: int = Query(...), id: int = Query(...)):
    check_connected()
    result = await bridge_service.port_status(resource_type, id)
    check_bridge_ok(result, "Port status query failed")
    return ApiResponse(success=True, data=result, timestamp=time.time())
