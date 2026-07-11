"""home_presence feature 行为测试。

新模型不再依赖后台 sleep：BLE 事件只更新在场设备集合与"清空时间戳"，
离家判定交给 cron 巡检 handler，因此测试可以同步驱动、无需等待真实时间。
"""
from __future__ import annotations

import pytest

import app.src.features.home_presence as hp
from app.src.models import AppEvent, EventSource, FeatureContext


class RecordingScheduler:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict]] = []

    async def emit_from_feature(self, *, source_feature: str, event_type: str, payload: dict) -> None:
        self.emitted.append((event_type, payload))


def _context(scheduler: RecordingScheduler, event_type: str, payload: dict | None = None) -> FeatureContext:
    return FeatureContext(
        feature_name=hp.FEATURE_NAME,
        activation=AppEvent(event_type, EventSource.PLATFORM_WS, payload or {}),
        scheduler=scheduler,
        platform=None,
    )


@pytest.fixture(autouse=True)
def _reset_state():
    hp._state.devices = set()
    hp._state.is_away = False
    hp._state.empty_since = None
    yield
    hp._state.devices = set()
    hp._state.is_away = False
    hp._state.empty_since = None



@pytest.mark.asyncio
async def test_empty_ble_records_timestamp_but_not_away_yet() -> None:
    scheduler = RecordingScheduler()

    # in_range_list 为空 -> 记录清空时间戳，但还不判定离家
    await hp.handle_in_range_list(_context(scheduler, "ble_in_range_list", {"devices": [], "device_count": 0}))
    assert scheduler.emitted == []
    assert hp._state.empty_since is not None
    assert hp._state.is_away is False


@pytest.mark.asyncio
async def test_check_emits_away_after_delay(monkeypatch) -> None:
    monkeypatch.setattr(hp, "AWAY_DELAY_S", 180)
    scheduler = RecordingScheduler()

    # 模拟清空已经发生在 200 秒前
    monkeypatch.setattr(hp, "_now", lambda: 1000.0)
    await hp.handle_in_range_list(_context(scheduler, "ble_in_range_list", {"devices": [], "device_count": 0}))
    assert hp._state.empty_since == 1000.0

    # cron 巡检：此刻已超过阈值 -> 发布离家
    monkeypatch.setattr(hp, "_now", lambda: 1000.0 + 200)
    await hp.handle_presence_check(_context(scheduler, "home_presence.check"))

    assert scheduler.emitted == [("home.away", {"reason": "ble_empty_timeout"})]
    assert hp._state.is_away is True
    assert hp._state.empty_since is None


@pytest.mark.asyncio
async def test_check_does_not_emit_before_delay(monkeypatch) -> None:
    monkeypatch.setattr(hp, "AWAY_DELAY_S", 180)
    scheduler = RecordingScheduler()

    monkeypatch.setattr(hp, "_now", lambda: 1000.0)
    await hp.handle_in_range_list(_context(scheduler, "ble_in_range_list", {"devices": [], "device_count": 0}))

    # 才过 60 秒，未达阈值
    monkeypatch.setattr(hp, "_now", lambda: 1000.0 + 60)
    await hp.handle_presence_check(_context(scheduler, "home_presence.check"))

    assert scheduler.emitted == []
    assert hp._state.is_away is False


@pytest.mark.asyncio
async def test_device_back_before_delay_clears_timestamp(monkeypatch) -> None:
    monkeypatch.setattr(hp, "AWAY_DELAY_S", 180)
    scheduler = RecordingScheduler()

    monkeypatch.setattr(hp, "_now", lambda: 1000.0)
    await hp.handle_in_range_list(_context(scheduler, "ble_in_range_list", {"devices": [], "device_count": 0}))
    assert hp._state.empty_since == 1000.0

    # 阈值前重新进入区域 -> 清掉时间戳，且未曾离家所以不发回家事件
    await hp.handle_device_in_range(
        _context(scheduler, "ble_device_in_range", {"mac": "AA:BB:CC:DD:EE:FF", "rssi": -40})
    )
    assert hp._state.empty_since is None
    assert hp._state.is_away is False

    # 即便 cron 之后再巡检也不会误报
    monkeypatch.setattr(hp, "_now", lambda: 1000.0 + 9999)
    await hp.handle_presence_check(_context(scheduler, "home_presence.check"))
    assert scheduler.emitted == []
    assert hp._state.devices == {"AA:BB:CC:DD:EE:FF"}


@pytest.mark.asyncio
async def test_reconnect_after_away_emits_home_arrive(monkeypatch) -> None:
    monkeypatch.setattr(hp, "AWAY_DELAY_S", 180)
    scheduler = RecordingScheduler()

    monkeypatch.setattr(hp, "_now", lambda: 1000.0)
    await hp.handle_in_range_list(_context(scheduler, "ble_in_range_list", {"devices": [], "device_count": 0}))
    monkeypatch.setattr(hp, "_now", lambda: 1000.0 + 200)
    await hp.handle_presence_check(_context(scheduler, "home_presence.check"))
    assert hp._state.is_away is True

    await hp.handle_device_in_range(
        _context(scheduler, "ble_device_in_range", {"mac": "AA:BB:CC:DD:EE:FF", "rssi": -40})
    )
    assert ("home.arrive", {"reason": "ble_reconnect"}) in scheduler.emitted
    assert hp._state.is_away is False


@pytest.mark.asyncio
async def test_out_of_range_to_empty_records_timestamp(monkeypatch) -> None:
    scheduler = RecordingScheduler()

    await hp.handle_device_in_range(
        _context(scheduler, "ble_device_in_range", {"mac": "AA:BB:CC:DD:EE:FF", "rssi": -40})
    )
    assert hp._state.empty_since is None

    await hp.handle_device_out_of_range(
        _context(scheduler, "ble_device_out_of_range", {"mac": "AA:BB:CC:DD:EE:FF", "reason": 0})
    )
    # 清空后只记录时间戳，不立即离家
    assert hp._state.empty_since is not None
    assert scheduler.emitted == []


