"""Main API router — aggregates all sub-routers."""
from fastapi import APIRouter
from .hardware import router as hardware_router
from .gpio import router as gpio_router
from .signal import router as signal_router
from .uart import router as uart_router
from .port import router as port_router
from .ble import router as ble_router
from .system import router as system_router
from .custom_cmd import router as custom_cmd_router
from .pins import router as pins_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(hardware_router)
api_router.include_router(gpio_router)
api_router.include_router(signal_router)
api_router.include_router(uart_router)
api_router.include_router(port_router)
api_router.include_router(ble_router)
api_router.include_router(system_router)
api_router.include_router(custom_cmd_router)
api_router.include_router(pins_router)
