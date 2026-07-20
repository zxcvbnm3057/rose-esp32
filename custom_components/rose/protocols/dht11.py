"""DHT11 protocol over the Rose signal exchange API."""
from __future__ import annotations

from collections.abc import Sequence

DHT11_START_SIGNAL = [
    {"level": 0, "duration_us": 20_000},
    {"level": 1, "duration_us": 30},
]


class Dht11DecodeError(ValueError):
    """Raised when a captured signal is not a valid DHT11 frame."""


def decode_dht11_signal(edges: Sequence[dict[str, int]]) -> tuple[float, float]:
    """Decode temperature and humidity from exact-resolution captured edges."""
    high_pulses = []
    response_started = False
    for edge in edges:
        if int(edge.get("level", -1)) != 1:
            continue
        duration_us = int(edge.get("duration_us", 0))
        if not response_started:
            response_started = 65 <= duration_us <= 95
            continue
        if 10 <= duration_us <= 100:
            high_pulses.append(duration_us)
        if len(high_pulses) == 40:
            break
    if len(high_pulses) != 40:
        raise Dht11DecodeError("DHT11 response contains fewer than 40 data bits")

    frame = bytearray(5)
    for bit_index, duration_us in enumerate(high_pulses):
        if duration_us > 50:
            frame[bit_index // 8] |= 1 << (7 - bit_index % 8)

    if (sum(frame[:4]) & 0xFF) != frame[4]:
        raise Dht11DecodeError("DHT11 checksum mismatch")

    humidity = frame[0] + frame[1] / 10
    temperature = (frame[2] & 0x7F) + frame[3] / 10
    if frame[2] & 0x80:
        temperature = -temperature
    return temperature, humidity