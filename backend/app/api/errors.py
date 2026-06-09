"""Shared error helpers for API routes."""
from __future__ import annotations
import time
from fastapi import HTTPException
from ..services import bridge_service


class BridgeError(HTTPException):
    """Bridge communication failed (device unreachable or command failed)."""
    def __init__(self, detail: str = "Bridge communication failed"):
        super().__init__(status_code=502, detail=detail)


class DeviceNotConnectedError(HTTPException):
    """ESP32 device is not connected."""
    def __init__(self):
        super().__init__(status_code=503, detail="ESP32 device not connected")


def check_connected():
    """Raise 503 if device is not connected."""
    if not bridge_service.is_connected():
        raise DeviceNotConnectedError()


def check_bridge_ok(result, detail: str = "Bridge command failed"):
    """Raise 502 if bridge returned None or False."""
    if result is None or result is False:
        raise BridgeError(detail)
    return result
