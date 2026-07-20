"""Regression tests for the DHT11 decoder shipped in the HA integration."""
import importlib.util
from pathlib import Path
import sys

import pytest

MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "rose" / "protocols" / "dht11.py"
spec = importlib.util.spec_from_file_location("rose_dht11", MODULE_PATH)
assert spec and spec.loader
rose_dht11 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = rose_dht11
spec.loader.exec_module(rose_dht11)


def _signal_for(frame: bytes) -> list[dict[str, int]]:
    edges = [
        {"level": 0, "duration_us": 80},
        {"level": 1, "duration_us": 80},
    ]
    for byte in frame:
        for bit in range(7, -1, -1):
            edges.append({"level": 0, "duration_us": 50})
            edges.append({"level": 1, "duration_us": 70 if byte & (1 << bit) else 27})
    return edges


def test_decode_dht11_signal():
    frame = bytes([63, 4, 24, 7, (63 + 4 + 24 + 7) & 0xFF])
    signal = _signal_for(frame)
    signal.append({"level": 1, "duration_us": 70})
    assert rose_dht11.decode_dht11_signal(signal) == (24.7, 63.4)


def test_decode_negative_temperature():
    frame = bytes([45, 0, 0x82, 3, (45 + 0x82 + 3) & 0xFF])
    assert rose_dht11.decode_dht11_signal(_signal_for(frame)) == (-2.3, 45.0)


def test_reject_bad_checksum():
    with pytest.raises(rose_dht11.Dht11DecodeError, match="checksum"):
        rose_dht11.decode_dht11_signal(_signal_for(bytes([50, 0, 20, 0, 0])))


def test_start_signal_releases_line_before_capture():
    assert rose_dht11.DHT11_START_SIGNAL == [
        {"level": 0, "duration_us": 20_000},
        {"level": 1, "duration_us": 30},
    ]