"""TCL 空调红外协议编码（TAC09CHSD / 112-bit，已用真实抓包校对）。

参考：
- https://github.com/crankyoldgit/IRremoteESP8266/blob/master/src/ir_Tcl.h
- 本机实测帧（制冷28/风速1/关灯/省电）：23 CB 26 01 00 E4 03 03 00 00 00 00 00 FF

================================ 指令格式 ================================

一条完整指令 = 引导码 + 14 字节数据 + 收尾位，全程 38kHz 载波调制。

时序（mark=有载波，space=无载波）：

    引导码         3100us mark + 1600us space
    逻辑 1          500us mark + 1100us space
    逻辑 0          500us mark +  350us space
    收尾位         500us mark（之后进入帧间静默）

位/字节序：
    - 14 个字节按 byte0 -> byte13 顺序发送（字节序大端）
    - 每个字节内先发最低位 bit0（位序小端）
    - 共 14 x 8 = 112 个数据位

================================ 帧布局 =================================

字节序：  byte0  byte1  byte2  byte3  byte4  byte5  ... byte13
          └──────── 固定头 ───────┘  └──────── 状态区 + 校验 ────────┘

  byte | 7        6        5        4        3        2        1        0
  -----+--------------------------------------------------------------------
   0   |                      0x23   （固定头）
   1   |                      0xCB   （固定头）
   2   |                      0x26   （固定头）
   3   |                      0x01   （固定头）
   4   |                      0x00   （固定头）
   5   | 省电     灯光     1固定    -        定时使能  开关     -        -
       | econo   light(1=关) const            timerEn  power
   6   | -        强力     -        健康     ┌────── 模式 mode (bit0-3) ──────┐
       |          turbo            health    auto=8 cool=3 dry=2 fan=7 heat=1
   7   | -        -        -        -        ┌──── 温度 temp (bit0-3) ────┐
       |                                     编码值 = 31 - 摄氏度 (16~31°C)
   8   | -        -        ┌─ 垂直摆风 (bit3-5) ─┐ ┌──── 风速 fan (bit0-2) ────┐
       |                   on=111 off=000        auto0 睡眠1 风速1=2 风速2=3 风速3=5
   9   |                  定时档位（分钟 / 10，例：30 分钟 = 0x03）
  10   |                      0x00
  11   |                      0x00
  12   | 制热强力  -        -        -        水平摆风  -        -        -
       | turbo&!aux                          swingH(bit3)
  13   |              校验码 = (byte0 + byte1 + ... + byte12) & 0xFF

说明：
- 本机遥控器无半度功能，故不编码半度位。
- byte5 bit5 在所有实测帧中恒为 1，作为固定位写入模板。
- byte6 bit4（健康/health）尚未由抓包确认，按位置保留。
- 风速档位已用多帧确认：自动=0，睡眠/最低=1，风速1=2，风速2=3，风速3=5。
  （遥控器的“睡眠模式”即风速字段取值 1。）
- 强力(turbo) 主标志位在 byte6 bit6（制冷/制热/除湿/送风开强力均置）。
- byte12 bit7：制热模式下“开强力且辅热关”时置 1；辅热开启则清零。
  （辅热 aux_heat 是独立可控位，通过该位与 byte6 bit6 的组合区分。）
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

TCL_HDR_MARK_US = 3100
TCL_HDR_SPACE_US = 1600
TCL_BIT_MARK_US = 500
TCL_ONE_SPACE_US = 1100
TCL_ZERO_SPACE_US = 350
TCL_FRAME_LENGTH = 14
TCL_CARRIER_HZ = 38_000
TCL_DUTY_CYCLE = 0.33

TCL_TEMP_MIN_C = 16
TCL_TEMP_MAX_C = 31

# 模式 (byte6 bit0-3)
TCL_MODE_AUTO = 8
TCL_MODE_COOL = 3
TCL_MODE_DRY = 2
TCL_MODE_HEAT = 1
TCL_MODE_FAN = 7

# 风速 (byte8 bit0-2)。已用多帧确认：自动=0、睡眠/最低=1、风速1=2、风速2=3、风速3=5。
# MIN(=1) 对应遥控器的“睡眠模式”。
TCL_FAN_AUTO = 0
TCL_FAN_MIN = 1
TCL_FAN_LOW = 2
TCL_FAN_MED = 3
TCL_FAN_HIGH = 5

# 垂直摆风 (byte8 bit3-5)
TCL_SWING_V_OFF = 0b000
TCL_SWING_V_ON = 0b111

# 固定头 + 清零模板（14 字节，最后一字节为校验）
# byte5 bit5 在所有实测帧中恒为 1，作为固定位放入模板。
TCL_BASE_STATE = bytes([
    0x23,
    0xCB,
    0x26,
    0x01,
    0x00,
    0x20,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
])


class TclPowerState(str, Enum):
    OFF = "off"
    ON = "on"


class TclHvacMode(str, Enum):
    AUTO = "auto"
    COOL = "cool"
    HEAT = "heat"
    DRY = "dry"
    FAN_ONLY = "fan_only"


class TclFanMode(str, Enum):
    AUTO = "auto"
    MIN = "min"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TclSwingVertical(str, Enum):
    OFF = "off"
    ON = "on"


class TclSwingHorizontal(str, Enum):
    OFF = "off"
    ON = "on"


@dataclass(frozen=True, slots=True)
class TclState:
    power: TclPowerState
    mode: TclHvacMode
    temperature_c: float
    fan: TclFanMode = TclFanMode.AUTO
    swing_vertical: TclSwingVertical = TclSwingVertical.ON
    swing_horizontal: TclSwingHorizontal = TclSwingHorizontal.OFF
    econo: bool = False
    health: bool = False
    turbo: bool = False
    light: bool = True
    timer_minutes: int = 0
    aux_heat: bool = False


def _set_bit(byte_value: int, bit: int, enabled: bool) -> int:
    if enabled:
        return byte_value | (1 << bit)
    return byte_value & ~(1 << bit)


def _set_bits(byte_value: int, offset: int, width: int, value: int) -> int:
    mask = ((1 << width) - 1) << offset
    byte_value &= ~mask
    byte_value |= (value << offset) & mask
    return byte_value


def _encode_temp(temp_c: float) -> tuple[int, bool]:
    safe = min(float(TCL_TEMP_MAX_C), max(float(TCL_TEMP_MIN_C), temp_c))
    half_steps = int(round(safe * 2))
    half_degree = bool(half_steps & 1)
    whole_temp = half_steps // 2
    encoded = TCL_TEMP_MAX_C - whole_temp
    return encoded, half_degree


def _mode_to_native(mode: TclHvacMode) -> int:
    return {
        TclHvacMode.AUTO: TCL_MODE_AUTO,
        TclHvacMode.COOL: TCL_MODE_COOL,
        TclHvacMode.HEAT: TCL_MODE_HEAT,
        TclHvacMode.DRY: TCL_MODE_DRY,
        TclHvacMode.FAN_ONLY: TCL_MODE_FAN,
    }[mode]


def _fan_to_native(fan: TclFanMode) -> int:
    return {
        TclFanMode.AUTO: TCL_FAN_AUTO,
        TclFanMode.MIN: TCL_FAN_MIN,
        TclFanMode.LOW: TCL_FAN_LOW,
        TclFanMode.MEDIUM: TCL_FAN_MED,
        TclFanMode.HIGH: TCL_FAN_HIGH,
    }[fan]


def _checksum(frame: bytearray) -> int:
    return sum(frame[:-1]) & 0xFF


def encode_tcl_frame(state: TclState) -> bytes:
    frame = bytearray(TCL_BASE_STATE)

    # Byte 5: 开关 bit2, 定时使能 bit3, 灯光 bit6（1=关灯）, 省电 bit7（bit5 固定，见模板）
    frame[5] = _set_bit(frame[5], 2, state.power == TclPowerState.ON)
    frame[5] = _set_bit(frame[5], 3, state.timer_minutes > 0)
    frame[5] = _set_bit(frame[5], 6, not state.light)
    frame[5] = _set_bit(frame[5], 7, state.econo)

    # Byte 6: 模式 bit0-3, 健康 bit4, 强力 bit6
    frame[6] = _set_bits(frame[6], 0, 4, _mode_to_native(state.mode))
    frame[6] = _set_bit(frame[6], 4, state.health)
    frame[6] = _set_bit(frame[6], 6, state.turbo)

    # Byte 7: 温度 16~31 -> 0x0F~0x00
    temp_encoded, _half_degree = _encode_temp(state.temperature_c)
    frame[7] = _set_bits(frame[7], 0, 4, temp_encoded)

    # Byte 8: 风速 bit0-2, 垂直摆风 bit3-5
    native_fan = TCL_FAN_HIGH if state.mode == TclHvacMode.FAN_ONLY and state.fan == TclFanMode.AUTO else _fan_to_native(state.fan)
    frame[8] = _set_bits(frame[8], 0, 3, native_fan)
    swing_v = TCL_SWING_V_ON if state.swing_vertical == TclSwingVertical.ON else TCL_SWING_V_OFF
    frame[8] = _set_bits(frame[8], 3, 3, swing_v)

    # Byte 9: 定时档位（分钟/10）
    frame[9] = (max(0, state.timer_minutes) // 10) & 0xFF

    # Byte 12: 水平摆风 bit3; 制热强力且非辅热时 bit7=1
    # 实测：制热模式下开强力、且辅热关闭时 byte12 bit7=1；
    # 一旦辅热开启，该位清零（除湿/制冷强力也不置此位）。
    frame[12] = _set_bit(frame[12], 3, state.swing_horizontal == TclSwingHorizontal.ON)
    frame[12] = _set_bit(
        frame[12], 7,
        state.mode == TclHvacMode.HEAT and state.turbo and not state.aux_heat,
    )

    frame[-1] = _checksum(frame)
    return bytes(frame)


def _byte_to_lsb_first_bits(byte_value: int) -> list[int]:
    return [(byte_value >> bit) & 0x01 for bit in range(8)]


def encode_tcl_ir_signal(state: TclState) -> tuple[list[dict[str, int]], int, float]:
    frame = encode_tcl_frame(state)
    signal: list[dict[str, int]] = [
        {"level": 1, "duration_us": TCL_HDR_MARK_US},
        {"level": 0, "duration_us": TCL_HDR_SPACE_US},
    ]
    for byte_value in frame:
        for bit in _byte_to_lsb_first_bits(byte_value):
            signal.append({"level": 1, "duration_us": TCL_BIT_MARK_US})
            signal.append({"level": 0, "duration_us": TCL_ONE_SPACE_US if bit else TCL_ZERO_SPACE_US})
    signal.append({"level": 1, "duration_us": TCL_BIT_MARK_US})
    return signal, TCL_CARRIER_HZ, TCL_DUTY_CYCLE
