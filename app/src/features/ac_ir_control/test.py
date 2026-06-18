from __future__ import annotations

from fastapi.testclient import TestClient

from app.src.main import create_app
from app.src.features.ac_ir_control.protocol.tcl import (
    TCL_CARRIER_HZ,
    TCL_DUTY_CYCLE,
    TclFanMode,
    TclHvacMode,
    TclPowerState,
    TclState,
    TclSwingHorizontal,
    TclSwingVertical,
    encode_tcl_frame,
    encode_tcl_ir_signal,
)


def test_encode_tcl_frame_generates_checksum_and_state_fields() -> None:
    frame = encode_tcl_frame(
        TclState(
            power=TclPowerState.ON,
            mode=TclHvacMode.COOL,
            temperature_c=26.0,
            fan=TclFanMode.MEDIUM,
        )
    )

    assert len(frame) == 14
    assert frame[0:5] == bytes([0x23, 0xCB, 0x26, 0x01, 0x00])
    assert frame[-1] == (sum(frame[:-1]) & 0xFF)
    assert frame[5] & (1 << 2)  # power on (bit2)
    assert (frame[6] & 0x0F) == 3  # cool (bit0-3)
    assert (frame[7] & 0x0F) == (31 - 26)  # 26C -> 0x05


def test_encode_tcl_frame_matches_real_captures() -> None:
    # 真实 RMT 抓包，逐字节钉死已确认的位布局。
    # 每个 case 的状态参数都对应一次真实遥控按键抓到的完整帧。
    cases = [
        (
            "23 CB 26 01 00 E4 03 03 00 00 00 00 00 FF",
            TclState(
                power=TclPowerState.ON, mode=TclHvacMode.COOL, temperature_c=28.0,
                swing_vertical=TclSwingVertical.OFF, econo=True, light=False,
            ),
        ),
        (
            "23 CB 26 01 00 E4 03 06 38 00 00 00 08 42",
            TclState(
                power=TclPowerState.ON, mode=TclHvacMode.COOL, temperature_c=25.0,
                swing_vertical=TclSwingVertical.ON, swing_horizontal=TclSwingHorizontal.ON,
                econo=True, light=False,
            ),
        ),
        (
            "23 CB 26 01 00 24 01 01 38 00 00 00 00 73",
            TclState(
                power=TclPowerState.ON, mode=TclHvacMode.HEAT, temperature_c=30.0,
                swing_vertical=TclSwingVertical.ON, light=True,
            ),
        ),
        (
            "23 CB 26 01 00 64 42 08 3A 00 00 00 00 FD",
            TclState(
                power=TclPowerState.ON, mode=TclHvacMode.DRY, temperature_c=23.0,
                swing_vertical=TclSwingVertical.ON, fan=TclFanMode.LOW, turbo=True, light=False,
            ),
        ),
        (
            "23 CB 26 01 00 24 07 08 3D 00 00 00 00 85",
            TclState(
                power=TclPowerState.ON, mode=TclHvacMode.FAN_ONLY, temperature_c=23.0,
                swing_vertical=TclSwingVertical.ON, fan=TclFanMode.HIGH, light=True,
            ),
        ),
        (
            "23 CB 26 01 00 2C 07 08 3D 03 00 00 00 90",
            TclState(
                power=TclPowerState.ON, mode=TclHvacMode.FAN_ONLY, temperature_c=23.0,
                swing_vertical=TclSwingVertical.ON, fan=TclFanMode.HIGH, light=True,
                timer_minutes=30,
            ),
        ),
        (
            "23 CB 26 01 00 20 07 08 3D 00 00 00 00 81",
            TclState(
                power=TclPowerState.OFF, mode=TclHvacMode.FAN_ONLY, temperature_c=23.0,
                swing_vertical=TclSwingVertical.ON, fan=TclFanMode.HIGH, light=True,
            ),
        ),
        (
            # "按了开启"：开机帧
            "23 CB 26 01 00 64 07 08 3D 00 00 00 00 C5",
            TclState(
                power=TclPowerState.ON, mode=TclHvacMode.FAN_ONLY, temperature_c=23.0,
                swing_vertical=TclSwingVertical.ON, fan=TclFanMode.HIGH, light=False,
            ),
        ),
    ]
    for expected_hex, state in cases:
        expected = bytes(int(b, 16) for b in expected_hex.split())
        assert encode_tcl_frame(state) == expected, expected_hex


def test_encode_tcl_frame_modes_match_real_captures() -> None:
    # 四帧模式抓包，确认 cool=3/heat=1/dry=2/fan=7/auto=8，
    # 以及制热+强力的 byte12 bit7 联动位。
    cases = [
        (
            "23 CB 26 01 00 24 08 08 00 00 00 00 00 49",
            TclState(
                power=TclPowerState.ON, mode=TclHvacMode.AUTO, temperature_c=23.0,
                fan=TclFanMode.AUTO, swing_vertical=TclSwingVertical.OFF, light=True,
            ),
        ),
        (
            "23 CB 26 01 00 64 03 06 00 00 00 00 00 82",
            TclState(
                power=TclPowerState.ON, mode=TclHvacMode.COOL, temperature_c=25.0,
                fan=TclFanMode.AUTO, swing_vertical=TclSwingVertical.OFF, light=False,
            ),
        ),
        (
            "23 CB 26 01 00 64 07 08 05 00 00 00 00 8D",
            TclState(
                power=TclPowerState.ON, mode=TclHvacMode.FAN_ONLY, temperature_c=23.0,
                fan=TclFanMode.HIGH, swing_vertical=TclSwingVertical.OFF, light=False,
            ),
        ),
        (
            # 制热 + 强力（非辅热）：byte6 bit6=1 且 byte12 bit7=1
            "23 CB 26 01 00 64 41 01 00 00 00 00 80 3B",
            TclState(
                power=TclPowerState.ON, mode=TclHvacMode.HEAT, temperature_c=30.0,
                fan=TclFanMode.AUTO, swing_vertical=TclSwingVertical.OFF, turbo=True, light=False,
            ),
        ),
    ]
    for expected_hex, state in cases:
        expected = bytes(int(b, 16) for b in expected_hex.split())
        assert encode_tcl_frame(state) == expected, expected_hex


def test_encode_tcl_frame_turbo_aux_heat_match_real_captures() -> None:
    # 强力/辅热差分抓包，定死 byte6 bit6(强力) 与 byte12 bit7(制热强力且非辅热)。
    cases = [
        # 制热 强力 + 辅热：byte6.6=1, byte12.7=0
        ("23 CB 26 01 00 64 41 01 00 00 00 00 00 BB",
         dict(mode=TclHvacMode.HEAT, temperature_c=30.0, turbo=True, aux_heat=True)),
        # 制热 仅强力（辅热关）：byte6.6=1, byte12.7=1
        ("23 CB 26 01 00 64 41 01 00 00 00 00 80 3B",
         dict(mode=TclHvacMode.HEAT, temperature_c=30.0, turbo=True, aux_heat=False)),
        # 制热 仅辅热（强力关）：byte6.6=0, byte12.7=0
        ("23 CB 26 01 00 64 01 01 00 00 00 00 00 7B",
         dict(mode=TclHvacMode.HEAT, temperature_c=30.0, turbo=False, aux_heat=True)),
        # 制冷 强力：byte6.6=1, byte12.7=0
        ("23 CB 26 01 00 64 43 0F 05 00 00 00 00 D0",
         dict(mode=TclHvacMode.COOL, temperature_c=16.0, fan=TclFanMode.HIGH, turbo=True)),
        # 除湿 强力：byte6.6=1, byte12.7=0
        ("23 CB 26 01 00 64 42 08 02 00 00 00 00 C5",
         dict(mode=TclHvacMode.DRY, temperature_c=23.0, fan=TclFanMode.LOW, turbo=True)),
        # 送风 强力：byte6.6=1, byte12.7=0
        ("23 CB 26 01 00 64 47 08 05 00 00 00 00 CD",
         dict(mode=TclHvacMode.FAN_ONLY, temperature_c=23.0, fan=TclFanMode.HIGH, turbo=True)),
    ]
    for expected_hex, kw in cases:
        expected = bytes(int(b, 16) for b in expected_hex.split())
        state = TclState(
            power=TclPowerState.ON, swing_vertical=TclSwingVertical.OFF, light=False, **kw,
        )
        assert encode_tcl_frame(state) == expected, expected_hex


def test_encode_tcl_frame_fan_speeds_match_real_captures() -> None:
    # 四帧风速抓包（制冷25/省电/关灯/垂直摆风关），仅风速不同。
    # 实测确认：自动=0, 睡眠/最低=1, 风速1=2, 风速2=3, 风速3=5。
    base = dict(
        power=TclPowerState.ON,
        mode=TclHvacMode.COOL,
        temperature_c=25.0,
        swing_vertical=TclSwingVertical.OFF,
        econo=True,
        light=False,
    )
    cases = [
        ("23 CB 26 01 00 E4 03 06 00 00 00 00 00 02", TclFanMode.AUTO),
        ("23 CB 26 01 00 E4 03 06 01 00 00 00 00 03", TclFanMode.MIN),
        ("23 CB 26 01 00 E4 03 06 02 00 00 00 00 04", TclFanMode.LOW),
        ("23 CB 26 01 00 E4 03 06 03 00 00 00 00 05", TclFanMode.MEDIUM),
        ("23 CB 26 01 00 E4 03 06 05 00 00 00 00 07", TclFanMode.HIGH),
    ]
    for expected_hex, fan in cases:
        expected = bytes(int(b, 16) for b in expected_hex.split())
        assert encode_tcl_frame(TclState(fan=fan, **base)) == expected, expected_hex


def test_encode_tcl_frame_sleep_mode_matches_real_captures() -> None:
    # 睡眠模式实测 = 风速字段取值 1（TclFanMode.MIN）。
    # 睡眠开（省电开）：byte8=01；睡眠关（省电关）：byte8=00。
    sleep_on = encode_tcl_frame(
        TclState(
            power=TclPowerState.ON, mode=TclHvacMode.COOL, temperature_c=25.0,
            fan=TclFanMode.MIN, swing_vertical=TclSwingVertical.OFF, econo=True, light=False,
        )
    )
    assert sleep_on == bytes.fromhex("23 CB 26 01 00 E4 03 06 01 00 00 00 00 03".replace(" ", ""))

    sleep_off = encode_tcl_frame(
        TclState(
            power=TclPowerState.ON, mode=TclHvacMode.COOL, temperature_c=25.0,
            fan=TclFanMode.AUTO, swing_vertical=TclSwingVertical.OFF, econo=False, light=False,
        )
    )
    assert sleep_off == bytes.fromhex("23 CB 26 01 00 64 03 06 00 00 00 00 00 82".replace(" ", ""))


def test_encode_tcl_ir_signal_builds_mark_space_sequence() -> None:
    signal, carrier_hz, duty_cycle = encode_tcl_ir_signal(
        TclState(
            power=TclPowerState.ON,
            mode=TclHvacMode.AUTO,
            temperature_c=24.0,
            fan=TclFanMode.AUTO,
        )
    )

    assert carrier_hz == TCL_CARRIER_HZ
    assert duty_cycle == TCL_DUTY_CYCLE
    assert signal[0] == {"level": 1, "duration_us": 3100}
    assert signal[1] == {"level": 0, "duration_us": 1600}
    assert signal[2]["level"] == 1
    assert signal[3]["level"] == 0
    assert signal[-1] == {"level": 1, "duration_us": 500}


def test_http_trigger_rejects_unknown_command() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post("/app/ac/ir/control", json={"room": "living_room", "mode": "invalid"})
    assert response.status_code == 503
