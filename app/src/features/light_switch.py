"""灯控 feature。

功能：
- 提供 HTTP 接口 `POST /app/lights/switch`
- 请求参数：
    - `room`: `living_room` | `bedroom`
    - `action`: `on` | `off`
- 收到请求后，向 UART1 发送预定义灯控指令

调用示例：
POST /app/lights/switch
{
    "room": "living_room",
    "action": "on"
}
"""
from __future__ import annotations

import base64
import logging
from enum import Enum

from pydantic import BaseModel

from app.src.models import DeliveryMode, EventSubscription, FeatureContext, FeatureSpec

ENABLED = True
UART_ID = 1
logger = logging.getLogger(__name__)


class RoomName(str, Enum):
    LIVING_ROOM = "living_room"
    BEDROOM = "bedroom"


class SwitchAction(str, Enum):
    ON = "on"
    OFF = "off"


class LightSwitchRequest(BaseModel):
    room: RoomName
    action: SwitchAction


def _encode_hex_command(hex_payload: str) -> str:
    return base64.b64encode(bytes.fromhex(hex_payload)).decode("ascii")


LIGHT_COMMANDS_HEX: dict[RoomName, dict[SwitchAction, str]] = {
    RoomName.LIVING_ROOM: {
        SwitchAction.ON: "fd 09 D3 F4 B3 60 df",
        SwitchAction.OFF: "fd 01 D3 F4 BB 60 df",
    },
    RoomName.BEDROOM: {
        SwitchAction.ON: "fd 01 B6 33 A8 60 df",
        SwitchAction.OFF: "fd 01 B6 33 9E 60 df",
    },
}

LIGHT_COMMANDS_BASE64: dict[RoomName, dict[SwitchAction, str]] = {
    room: {
        action: _encode_hex_command(command_hex)
        for action, command_hex in actions.items()
    }
    for room, actions in LIGHT_COMMANDS_HEX.items()
}


async def handle(context: FeatureContext) -> None:
    request = LightSwitchRequest.model_validate(context.activation.payload)
    data_base64 = LIGHT_COMMANDS_BASE64[request.room][request.action]
    result = await context.platform.uart_send(UART_ID, data_base64=data_base64)
    logger.info(
        "light switch sent room=%s action=%s uart=%s result=%s",
        request.room.value,
        request.action.value,
        UART_ID,
        result,
    )


FEATURE = FeatureSpec(
    name="light_switch",
    enabled=ENABLED,
    subscriptions=[
        EventSubscription.http(
            path="/lights/switch",
            request_model=LightSwitchRequest,
            delivery_mode=DeliveryMode.QUEUE,
            description="Switch living room or bedroom light via UART1.",
        ),
    ],
    handler=handle,
)