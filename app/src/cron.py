"""Small cron expression helper used by the app scheduler.

Supported format: five fields, minute hour day-of-month month day-of-week.
Each field supports `*`, `*/n`, `a`, `a,b,c`, and `a-b`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


_FIELD_RANGES = (
    (0, 59),   # minute
    (0, 23),   # hour
    (1, 31),   # day of month
    (1, 12),   # month
    (0, 6),    # day of week, Python Monday=0
)


def _parse_field(raw: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            raise ValueError("empty cron field part")
        if part == "*":
            values.update(range(minimum, maximum + 1))
        elif part.startswith("*/"):
            step = int(part[2:])
            if step <= 0:
                raise ValueError("cron step must be positive")
            values.update(range(minimum, maximum + 1, step))
        elif "-" in part:
            start_s, end_s = part.split("-", 1)
            start, end = int(start_s), int(end_s)
            if start > end:
                raise ValueError("cron range start must be <= end")
            values.update(range(start, end + 1))
        else:
            values.add(int(part))
    invalid = [value for value in values if value < minimum or value > maximum]
    if invalid:
        raise ValueError(f"cron value out of range: {invalid[0]}")
    return values


@dataclass(frozen=True, slots=True)
class CronExpr:
    expression: str

    def __post_init__(self) -> None:
        fields = self.expression.split()
        if len(fields) != 5:
            raise ValueError("cron expression must contain 5 fields")
        parsed = tuple(_parse_field(raw, *bounds) for raw, bounds in zip(fields, _FIELD_RANGES, strict=True))
        object.__setattr__(self, "_parsed", parsed)

    def matches(self, dt: datetime) -> bool:
        minute, hour, day, month, weekday = self._parsed
        return (
            dt.minute in minute
            and dt.hour in hour
            and dt.day in day
            and dt.month in month
            and dt.weekday() in weekday
        )

    def next_after(self, dt: datetime) -> datetime:
        cursor = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        deadline = cursor + timedelta(days=366 * 5)
        while cursor <= deadline:
            if self.matches(cursor):
                return cursor
            cursor += timedelta(minutes=1)
        raise ValueError(f"no future time found for cron expression: {self.expression}")
