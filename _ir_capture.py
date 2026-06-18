"""一次性 RMT 硬件抓包 + TCL 解码对照脚本。

流程：
1. 解绑并把 GPIO4 配置成 SIGNAL 模式（RMT 抓包要求）
2. 通过 signal/exchange（tx 留空）开 RMT RX 窗口
3. 窗口内由人按一次遥控键
4. 把捕获边沿按 TCL 时序还原成 14 字节，并与当前协议栈编码对照

HX1838B 输出反相：mark(载波)->低电平，space(空闲)->高电平。
解码只依赖 mark/space 交替的“持续时间”，不依赖电平极性。
"""
from __future__ import annotations

import sys
import time

import httpx

from app.src.features.ac_ir_control.protocol.tcl import (
    TclFanMode,
    TclHvacMode,
    TclPowerState,
    TclState,
    TclSwingHorizontal,
    TclSwingVertical,
    encode_tcl_frame,
)

BASE = "http://127.0.0.1:8000/api/v1"
GPIO = 4
# 一帧 TCL 红外仅 ~130ms。固件 RX-only 路径会“死等”整个窗口跑完才返回，
# 窗口设得太长会让整条链路同步阻塞过久，被上游判 502。
# 1.5s 足够在开窗后立即按一下遥控。
RX_TOTAL_US = 1_500_000
RX_MAX_EDGES = 256


def _post(client: httpx.Client, path: str, body: dict) -> dict:
    resp = client.post(f"{BASE}{path}", json=body)
    resp.raise_for_status()
    return resp.json()


def decode_edges(edges: list[dict]) -> list[int]:
    durations = [int(e["duration_us"]) for e in edges]
    # 找引导码：mark≈3100, space≈1600
    start = None
    for i in range(len(durations) - 1):
        if 2600 <= durations[i] <= 3600 and 1300 <= durations[i + 1] <= 1900:
            start = i + 2
            break
    if start is None:
        raise SystemExit("未找到 TCL 引导码，抓包可能失败或不是该协议")

    bits: list[int] = []
    i = start
    while i + 1 < len(durations):
        space = durations[i + 1]
        # 数据结束：出现异常大的 space（帧间隔）或剩余不足
        if space > 4000:
            break
        bits.append(1 if space > 700 else 0)
        i += 2
        if len(bits) >= 112:
            break

    out: list[int] = []
    for b in range(0, len(bits), 8):
        chunk = bits[b : b + 8]
        value = 0
        for j, bit in enumerate(chunk):
            value |= bit << j
        out.append(value)
    return out


def main() -> None:
    with httpx.Client(timeout=20.0) as client:
        # 清理 GPIO4 占用并切 SIGNAL 模式
        try:
            _post(client, "/port/unbind", {"resource_type": 0, "id": GPIO})
        except Exception:
            pass
        _post(client, f"/gpio/{GPIO}/config", {"mode": 4})
        print(f"GPIO{GPIO} 已切到 SIGNAL 模式")

        for n in (3, 2, 1):
            print(f"准备抓包... {n}（手指放遥控键上，听到提示立即按）", flush=True)
            time.sleep(1)
        print(">>> 现在立即按一次遥控键（窗口 1.5 秒）<<<", flush=True)

        result = _post(
            client,
            f"/gpio/{GPIO}/signal/exchange",
            {
                "tx_signal": [],
                "delay_us": 0,
                "carrier_hz": 0,
                "duty_cycle": 0.5,
                "rx_total_us": RX_TOTAL_US,
                "rx_max_edges": RX_MAX_EDGES,
                "resolution": "exact",
            },
        )

    data = result.get("data", {})
    edges = data.get("edges", [])
    print(f"捕获边沿数: {len(edges)}")
    if not edges:
        raise SystemExit("没有捕获到任何边沿，检查接线/对准/距离")

    print("raw durations:", " ".join(str(int(e["duration_us"])) for e in edges))

    decoded = decode_edges(edges)
    print("解码字节 :", " ".join(f"{b:02X}" for b in decoded))
    print("解码长度 :", len(decoded))
    if len(decoded) == 14:
        calc = sum(decoded[:-1]) & 0xFF
        print(f"校验位   : 收到=0x{decoded[-1]:02X} 计算=0x{calc:02X} {'OK' if calc == decoded[-1] else '不一致'}")

    expected = encode_tcl_frame(
        TclState(
            power=TclPowerState.ON,
            mode=TclHvacMode.COOL,
            temperature_c=28.0,
            fan=TclFanMode.LOW,
            swing_vertical=TclSwingVertical.ON,
            swing_horizontal=TclSwingHorizontal.ON,
            econo=True,
            health=False,
            turbo=False,
            light=False,
        )
    )
    print("编码字节 :", " ".join(f"{b:02X}" for b in expected))

    if len(decoded) == len(expected):
        diff = [i for i in range(len(decoded)) if decoded[i] != expected[i]]
        if not diff:
            print("结果: 完全一致")
        else:
            print("差异字节索引:", diff)
            for i in diff:
                print(f"  byte{i}: 实测=0x{decoded[i]:02X}({decoded[i]:08b}) 编码=0x{expected[i]:02X}({expected[i]:08b})")


if __name__ == "__main__":
    sys.exit(main())
