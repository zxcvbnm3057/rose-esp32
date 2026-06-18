"""空调红外控制 feature。

功能：
- 提供 HTTP 接口 `POST /app/ac/ir/control`
- 请求参数：
    - `room`: `living_room` | `bedroom`（必填，房间→GPIO/协议映射）
    - `power`: `on` | `off`（默认 `on`）
    - `mode`: `auto` | `cool` | `heat` | `dry` | `fan_only`（默认 `cool`）
    - `temperature_c`: 16.0 ~ 31.0（默认 26.0；本机遥控无半度，按整度处理）
    - `fan`: `auto` | `min` | `low` | `medium` | `high`（默认 `auto`；`min` 即睡眠/最低风）
    - `swing_vertical`: `on` | `off`（上下扫风，默认 `on`）
    - `swing_horizontal`: `on` | `off`（左右扫风，默认 `off`）
    - `econo`: 省电模式，`true` | `false`（默认 `false`）
    - `health`: 健康/负离子，`true` | `false`（默认 `false`；本机遥控可能无此功能）
    - `turbo`: 强力模式，`true` | `false`（默认 `false`）
    - `light`: 面板灯光，`true`=亮 | `false`=灭（默认 `true`）
    - `timer_minutes`: 定时关机分钟数，0 ~ 1440（默认 0=不定时；按 10 分钟一档取整）
    - `aux_heat`: 电辅热，`true` | `false`（默认 `false`；仅制热模式有效）
- 收到请求后，根据房间映射找到对应 GPIO 和厂商协议编码器
- 目前先实现 TCL 整帧协议编码，并通过 `signal_tx` 携带载波参数发送完整红外波形

最小调用示例（其余字段取默认值）：
POST /app/ac/ir/control
{
    "room": "living_room",
    "power": "on",
    "mode": "cool",
    "temperature_c": 26,
    "fan": "auto"
}

完整调用示例（列出全部字段）：
POST /app/ac/ir/control
{
    "room": "living_room",
    "power": "on",
    "mode": "heat",
    "temperature_c": 25,
    "fan": "high",
    "swing_vertical": "on",
    "swing_horizontal": "off",
    "econo": false,
    "health": false,
    "turbo": true,
    "light": true,
    "timer_minutes": 30,
    "aux_heat": true
}
"""

from __future__ import annotations

import logging
from enum import Enum

from pydantic import BaseModel, Field

from app.src.models import DeliveryMode, EventSubscription, FeatureContext, FeatureSpec

from .config import ROOM_BINDINGS
from .protocol import (
    TclFanMode,
    TclHvacMode,
    TclPowerState,
    TclState,
    TclSwingHorizontal,
    TclSwingVertical,
    encode_tcl_ir_signal,
)

ENABLED = True
logger = logging.getLogger(__name__)


class RoomName(str, Enum):
    LIVING_ROOM = "living_room"
    BEDROOM = "bedroom"


class AcIrControlRequest(BaseModel):
    room: RoomName
    power: TclPowerState = TclPowerState.ON
    mode: TclHvacMode = TclHvacMode.COOL
    temperature_c: float = Field(default=26.0, ge=16.0, le=31.0)
    fan: TclFanMode = TclFanMode.AUTO
    swing_vertical: TclSwingVertical = TclSwingVertical.ON
    swing_horizontal: TclSwingHorizontal = TclSwingHorizontal.OFF
    econo: bool = False
    health: bool = False
    turbo: bool = False
    light: bool = True
    timer_minutes: int = Field(default=0, ge=0, le=1440)
    aux_heat: bool = False


async def handle(context: FeatureContext) -> None:
    request = AcIrControlRequest.model_validate(context.activation.payload)
    binding = ROOM_BINDINGS[request.room.value]
    if binding.protocol != "tcl":
        raise ValueError(f"Unsupported AC protocol: {binding.protocol}")

    state = TclState(
        power=request.power,
        mode=request.mode,
        temperature_c=request.temperature_c,
        fan=request.fan,
        swing_vertical=request.swing_vertical,
        swing_horizontal=request.swing_horizontal,
        econo=request.econo,
        health=request.health,
        turbo=request.turbo,
        light=request.light,
        timer_minutes=request.timer_minutes,
        aux_heat=request.aux_heat,
    )
    await _send_state(context, request.room.value, state)


async def _send_state(context: FeatureContext, room: str, state: TclState) -> None:
    binding = ROOM_BINDINGS[room]
    if binding.protocol != "tcl":
        raise ValueError(f"Unsupported AC protocol: {binding.protocol}")
    signal, carrier_hz, duty_cycle = encode_tcl_ir_signal(state)
    result = await context.platform.signal_tx(
        binding.gpio,
        signal,
        carrier_hz=carrier_hz,
        duty_cycle=duty_cycle,
    )
    logger.info(
        "ac ir state sent room=%s gpio=%s protocol=%s power=%s mode=%s temp=%.1f fan=%s result=%s",
        room,
        binding.gpio,
        binding.protocol,
        state.power.value,
        state.mode.value,
        state.temperature_c,
        state.fan.value,
        result,
    )


async def handle_home_away(context: FeatureContext) -> None:
    """离家：关闭所有房间的空调。"""
    logger.info("ac: home away -> turning off all air conditioners")
    off_state = TclState(
        power=TclPowerState.OFF,
        mode=TclHvacMode.COOL,
        temperature_c=26.0,
    )
    for room in ROOM_BINDINGS:
        await _send_state(context, room, off_state)


FEATURE = FeatureSpec(
    name="ac_ir_control",
    enabled=ENABLED,
    subscriptions=[
        EventSubscription.http(
            path="/ac/ir/control",
            request_model=AcIrControlRequest,
            delivery_mode=DeliveryMode.QUEUE,
            description="Send a raw IR air-conditioner command by room binding and command name.",
            handler=handle,
        ),
        EventSubscription.internal(
            "home.away",
            DeliveryMode.QUEUE,
            handler=handle_home_away,
        ),
    ],
)
