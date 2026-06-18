"""CronExpr 解析与调度时间计算测试。"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.src.cron import CronExpr


def test_every_minute_constructs_and_matches() -> None:
    # 回归：CronExpr 使用 slots=True dataclass，_parsed 必须有对应 slot，
    # 否则构造时 object.__setattr__ 会抛 AttributeError，导致 cron 永不触发。
    cron = CronExpr("* * * * *")
    now = datetime(2026, 6, 18, 22, 1, 23)
    assert cron.matches(now) is True
    assert cron.next_after(now) == datetime(2026, 6, 18, 22, 2, 0)


def test_step_field_next_after() -> None:
    cron = CronExpr("*/5 * * * *")
    now = datetime(2026, 6, 18, 22, 1, 23)
    assert cron.next_after(now) == datetime(2026, 6, 18, 22, 5, 0)


def test_specific_minute_hour() -> None:
    cron = CronExpr("30 9 * * *")
    now = datetime(2026, 6, 18, 22, 1, 0)
    assert cron.next_after(now) == datetime(2026, 6, 19, 9, 30, 0)


def test_range_and_list_fields() -> None:
    # weekday 字段沿用 Python 惯例（周一=0），故 "1,3,5" = 周二/周四/周六
    cron = CronExpr("0 9-17 * * 1,3,5")
    now = datetime(2026, 6, 18, 18, 0, 0)  # 周四(weekday=3)，已过 17:00
    nxt = cron.next_after(now)
    assert nxt.hour == 9 and nxt.minute == 0
    assert nxt.weekday() in (1, 3, 5)
    # 下一个命中应是周六 9:00
    assert nxt == datetime(2026, 6, 20, 9, 0, 0)


def test_invalid_field_count_raises() -> None:
    with pytest.raises(ValueError, match="5 fields"):
        CronExpr("* * * *")


def test_out_of_range_value_raises() -> None:
    with pytest.raises(ValueError, match="out of range"):
        CronExpr("99 * * * *")
