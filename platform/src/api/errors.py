"""Shared error helpers for API routes."""
from __future__ import annotations
import time
from typing import Optional
from fastapi import HTTPException
from ..services import bridge_service


# Firmware error codes (mirror of include/iot_agent.h IOT_ERR_*).
IOT_ERR_INVALID_ARG = 1
IOT_ERR_INVALID_STATE = 2
IOT_ERR_DRIVER = 3
IOT_ERR_RESOURCE_CONFLICT = 4
IOT_ERR_UNSUPPORTED = 5
IOT_ERR_NOT_FOUND = 6
IOT_ERR_RESOURCE_EXHAUSTED = 7
IOT_ERR_WRONG_MODE = 8
IOT_ERR_NOT_BOUND = 9
IOT_ERR_NO_MEM = 10
IOT_ERR_UNKNOWN_CMD = 0xFF

# Map each error code to (http_status, human-readable reason).
# 409 = caller can fix the request (wrong mode, not bound, bad arg);
# 502 = device-side failure (driver/resource/memory) the caller can't fix.
_ERROR_MAP: dict[int, tuple[int, str]] = {
    IOT_ERR_INVALID_ARG: (409, "参数非法（越界或超出取值范围）"),
    IOT_ERR_INVALID_STATE: (502, "设备状态异常"),
    IOT_ERR_DRIVER: (502, "设备底层驱动调用失败"),
    IOT_ERR_RESOURCE_CONFLICT: (409, "资源已被占用"),
    IOT_ERR_UNSUPPORTED: (501, "当前硬件/固件不支持该操作"),
    IOT_ERR_NOT_FOUND: (404, "目标资源或设备不存在"),
    IOT_ERR_RESOURCE_EXHAUSTED: (503, "设备资源耗尽（队列满或通道用尽）"),
    IOT_ERR_WRONG_MODE: (409, "引脚模式不匹配（请先将引脚配置为所需模式）"),
    IOT_ERR_NOT_BOUND: (409, "资源未绑定或未配置"),
    IOT_ERR_NO_MEM: (502, "设备内存不足"),
    IOT_ERR_UNKNOWN_CMD: (502, "设备不识别该命令"),
}


class BridgeError(HTTPException):
    """Bridge communication failed (device unreachable or command failed)."""
    def __init__(self, detail: str = "Bridge communication failed", status_code: int = 502):
        super().__init__(status_code=status_code, detail=detail)


class DeviceNotConnectedError(HTTPException):
    """ESP32 device is not connected."""
    def __init__(self):
        super().__init__(status_code=503, detail="ESP32 device not connected")


def check_connected():
    """Raise 503 if device is not connected."""
    if not bridge_service.is_connected():
        raise DeviceNotConnectedError()


def check_bridge_ok(result, detail: str = "Bridge command failed"):
    """Raise on bridge failure, surfacing the firmware error reason.

    If the bridge recorded a device error code for the last command, the
    HTTP status and message reflect that precise reason (e.g. WRONG_MODE
    -> 409 "引脚模式不匹配"). Otherwise it falls back to a generic 502
    with the caller-supplied ``detail`` (typically a timeout / no response).
    """
    if result is None or result is False:
        err_code: Optional[int] = bridge_service.get_last_error()
        if err_code is not None and err_code in _ERROR_MAP:
            status_code, reason = _ERROR_MAP[err_code]
            raise BridgeError(f"{detail}：{reason}", status_code=status_code)
        # Unknown code or timeout — keep the generic 502.
        raise BridgeError(detail)
    return result
