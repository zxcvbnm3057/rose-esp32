"""Hardware config endpoint."""
import time
from fastapi import APIRouter
from ..config import load_hardware_config
from ..models.schemas import ApiResponse

router = APIRouter(prefix="/hardware", tags=["hardware"])


@router.get("/config")
async def get_hardware_config():
    """Return the full hardware configuration."""
    return ApiResponse(success=True, data=load_hardware_config(), timestamp=time.time())
