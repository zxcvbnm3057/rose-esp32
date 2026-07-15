"""TCL TAC09CHSD 112-bit infrared encoder."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

TCL_BASE_STATE = bytes([0x23, 0xCB, 0x26, 0x01, 0x00, 0x20, 0, 0, 0, 0, 0, 0, 0, 0])


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


@dataclass(frozen=True, slots=True)
class TclState:
    power: TclPowerState
    mode: TclHvacMode
    temperature_c: float
    fan: TclFanMode = TclFanMode.AUTO
    swing_vertical: bool = True
    swing_horizontal: bool = False
    econo: bool = False
    health: bool = False
    turbo: bool = False
    light: bool = True
    timer_minutes: int = 0
    aux_heat: bool = False


def _set_bit(value: int, bit: int, enabled: bool) -> int:
    return value | (1 << bit) if enabled else value & ~(1 << bit)


def _set_bits(value: int, offset: int, width: int, field: int) -> int:
    mask = ((1 << width) - 1) << offset
    return (value & ~mask) | ((field << offset) & mask)


def encode_tcl_frame(state: TclState) -> bytes:
    frame = bytearray(TCL_BASE_STATE)
    frame[5] = _set_bit(frame[5], 2, state.power == TclPowerState.ON)
    frame[5] = _set_bit(frame[5], 3, state.timer_minutes > 0)
    frame[5] = _set_bit(frame[5], 6, not state.light)
    frame[5] = _set_bit(frame[5], 7, state.econo)
    mode = {
        TclHvacMode.AUTO: 8,
        TclHvacMode.COOL: 3,
        TclHvacMode.HEAT: 1,
        TclHvacMode.DRY: 2,
        TclHvacMode.FAN_ONLY: 7,
    }[state.mode]
    frame[6] = _set_bits(frame[6], 0, 4, mode)
    frame[6] = _set_bit(frame[6], 4, state.health)
    frame[6] = _set_bit(frame[6], 6, state.turbo)
    temperature = int(round(min(31.0, max(16.0, state.temperature_c))))
    frame[7] = _set_bits(frame[7], 0, 4, 31 - temperature)
    fan = {
        TclFanMode.AUTO: 0,
        TclFanMode.MIN: 1,
        TclFanMode.LOW: 2,
        TclFanMode.MEDIUM: 3,
        TclFanMode.HIGH: 5,
    }[state.fan]
    if state.mode == TclHvacMode.FAN_ONLY and state.fan == TclFanMode.AUTO:
        fan = 5
    frame[8] = _set_bits(frame[8], 0, 3, fan)
    frame[8] = _set_bits(frame[8], 3, 3, 0b111 if state.swing_vertical else 0)
    frame[9] = (max(0, min(1440, state.timer_minutes)) // 10) & 0xFF
    frame[12] = _set_bit(frame[12], 3, state.swing_horizontal)
    frame[12] = _set_bit(frame[12], 7, state.mode == TclHvacMode.HEAT and state.turbo and not state.aux_heat)
    frame[-1] = sum(frame[:-1]) & 0xFF
    return bytes(frame)


def encode_tcl_ir_signal(state: TclState) -> tuple[list[dict[str, int]], int, float]:
    signal = [{"level": 1, "duration_us": 3100}, {"level": 0, "duration_us": 1600}]
    for byte_value in encode_tcl_frame(state):
        for bit in range(8):
            signal.append({"level": 1, "duration_us": 500})
            signal.append({"level": 0, "duration_us": 1100 if (byte_value >> bit) & 1 else 350})
    signal.append({"level": 1, "duration_us": 500})
    return signal, 38_000, 0.33
