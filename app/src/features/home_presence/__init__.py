"""家居在场感知 feature（基于蓝牙区域内设备状态）。

功能：
- 订阅平台 BLE 事件，跟踪当前区域内的蓝牙设备集合：
    - `ble_in_range_list`       ：全量在场设备列表（覆盖式刷新）
    - `ble_device_in_range`     ：单个设备进入区域（已连接心跳 或 iOS 广播命中）
    - `ble_device_out_of_range` ：单个设备离开区域（在场超时）
- 在场设备清空时记录时间戳；由一个 cron 定时器周期性检测，
  当"无任何在场设备"持续超过 `AWAY_DELAY_S` 后，发布内部事件 `home.away`（离家）
- 当蓝牙设备重新进入区域（从离家状态恢复）时，发布内部事件 `home.arrive`（回家）

发布的内部事件（供其它 feature 订阅）：
- `home.away`  ：离家。light 关闭所有灯光，ac 关闭所有空调
- `home.arrive`：回家。light 打开客厅灯光

说明：
- 本 feature 只做"在场状态判定 + 事件编排"，不直接操作硬件
- 实际关灯/关空调/开灯动作由 `light_switch` 与 `ac_ir_control` 各自订阅上述事件完成
- 离家判定不使用后台 sleep 任务：BLE 事件只负责更新 peer 集合与"清空时间戳"，
  真正的超时判定交给 cron 定时器轮询，逻辑无状态、可重入、易测试
- 注意：框架 cron 为分钟级粒度，最快每分钟检测一次；相对 3 分钟阈值，
  最坏判定延迟在 1 分钟内，对离家场景足够
- 四个事件（3 个 BLE + 1 个 cron）分别注册独立 handler，
  演示「同一 feature 为不同事件订阅不同处理器」
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from app.src.models import DeliveryMode, EventSubscription, FeatureContext, FeatureSpec

ENABLED = True
FEATURE_NAME = "home_presence"
# 离家事件名（供 light_switch / ac_ir_control 订阅）
EVENT_HOME_AWAY = "home.away"
# 回家事件名
EVENT_HOME_ARRIVE = "home.arrive"
# 无任何蓝牙 peer 持续多久判定为离家（秒）
AWAY_DELAY_S = 3 * 60
# cron 巡检表达式：每分钟一次（框架 cron 最细为分钟级）
PRESENCE_CHECK_CRON = "* * * * *"
logger = logging.getLogger(__name__)


def _now() -> float:
    return time.monotonic()


@dataclass(slots=True)
class PresenceState:
    """在场状态。

    同一 feature 的 handler 由调度器串行执行，故无需加锁。
    """

    devices: set[str] = field(default_factory=set)
    # True 表示当前处于"已离家"状态
    is_away: bool = False
    # 在场设备清空那一刻的单调时间戳；有设备或已离家时为 None
    empty_since: float = _now()


_state = PresenceState()

def _mac_of(item: object) -> str | None:
    if isinstance(item, dict):
        mac = item.get("mac")
        return str(mac) if mac else None
    return str(item) if item else None


def _mark_present() -> None:
    """有设备在场：清掉空在场时间戳。"""
    _state.empty_since = None


def _mark_empty_if_needed() -> None:
    """无在场设备：首次清空时记录时间戳（已离家则不再重复记录）。"""
    if _state.devices or _state.is_away:
        _state.empty_since = None
        return
    if _state.empty_since is None:
        _state.empty_since = _now()


async def _on_device_present(context: FeatureContext) -> None:
    """有设备进入区域：清空时间戳；若此前已离家则发布回家事件。"""
    _mark_present()
    if _state.is_away:
        _state.is_away = False
        logger.info("home presence: BLE device back in range, emitting %s", EVENT_HOME_ARRIVE)
        await context.emit_event(EVENT_HOME_ARRIVE, {"reason": "ble_reconnect"})


async def handle_in_range_list(context: FeatureContext) -> None:
    """全量在场设备列表，覆盖式刷新当前在场集合。"""
    raw_devices = context.activation.payload.get("devices") or []
    macs = {mac for mac in (_mac_of(item) for item in raw_devices) if mac}
    _state.devices = macs
    logger.info("home presence: in_range_list -> %d device(s)", len(macs))
    if macs:
        await _on_device_present(context)
    else:
        _mark_empty_if_needed()


async def handle_device_in_range(context: FeatureContext) -> None:
    """单个设备进入区域。"""
    mac = _mac_of(context.activation.payload)
    if mac:
        _state.devices.add(mac)
    logger.info("home presence: device_in_range mac=%s total=%d", mac, len(_state.devices))
    await _on_device_present(context)


async def handle_device_out_of_range(context: FeatureContext) -> None:
    """单个设备离开区域。若清空则记录时间戳。"""
    mac = _mac_of(context.activation.payload)
    if mac:
        _state.devices.discard(mac)
    logger.info("home presence: device_out_of_range mac=%s total=%d", mac, len(_state.devices))
    if not _state.devices:
        _mark_empty_if_needed()


async def handle_presence_check(context: FeatureContext) -> None:
    """cron 巡检：无在场设备持续超过 AWAY_DELAY_S 即判定离家。"""
    if _state.devices or _state.is_away or _state.empty_since is None:
        return
    elapsed = _now() - _state.empty_since
    if elapsed < AWAY_DELAY_S:
        return
    _state.is_away = True
    _state.empty_since = None
    logger.info("home presence: no BLE device for %.0fs, emitting %s", elapsed, EVENT_HOME_AWAY)
    await context.emit_event(EVENT_HOME_AWAY, {"reason": "ble_empty_timeout"})


FEATURE = FeatureSpec(
    name=FEATURE_NAME,
    enabled=ENABLED,
    subscriptions=[
        EventSubscription.platform(
            "ble_in_range_list",
            DeliveryMode.QUEUE,
            handler=handle_in_range_list,
        ),
        EventSubscription.platform(
            "ble_device_in_range",
            DeliveryMode.QUEUE,
            handler=handle_device_in_range,
        ),
        EventSubscription.platform(
            "ble_device_out_of_range",
            DeliveryMode.QUEUE,
            handler=handle_device_out_of_range,
        ),
        EventSubscription.timer(
            event_type="home_presence.check",
            cron=PRESENCE_CHECK_CRON,
            delivery_mode=DeliveryMode.DEDUPE,
            handler=handle_presence_check,
        ),
    ],
)
