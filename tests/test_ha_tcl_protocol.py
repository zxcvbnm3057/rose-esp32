"""Regression tests for the TCL encoder shipped in the HA integration."""
import importlib.util
from pathlib import Path
import sys

MODULE_PATH = Path(__file__).parents[1] / "homeassistant" / "component" / "protocols" / "tcl.py"
spec = importlib.util.spec_from_file_location("rose_tcl", MODULE_PATH)
assert spec and spec.loader
rose_tcl = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = rose_tcl
spec.loader.exec_module(rose_tcl)

TclFanMode = rose_tcl.TclFanMode
TclHvacMode = rose_tcl.TclHvacMode
TclPowerState = rose_tcl.TclPowerState
TclState = rose_tcl.TclState
encode_tcl_frame = rose_tcl.encode_tcl_frame
encode_tcl_ir_signal = rose_tcl.encode_tcl_ir_signal


def test_known_tcl_capture():
    state = TclState(
        power=TclPowerState.ON,
        mode=TclHvacMode.COOL,
        temperature_c=25,
        fan=TclFanMode.MIN,
        swing_vertical=False,
        econo=True,
        light=False,
    )
    assert encode_tcl_frame(state) == bytes.fromhex("23 CB 26 01 00 E4 03 06 01 00 00 00 00 03")


def test_tcl_signal_fits_platform_limit():
    signal, carrier_hz, duty_cycle = encode_tcl_ir_signal(
        TclState(TclPowerState.ON, TclHvacMode.COOL, 26)
    )
    assert len(signal) == 227
    assert carrier_hz == 38000
    assert duty_cycle == 0.33
    assert signal[0] == {"level": 1, "duration_us": 3100}
    assert signal[-1] == {"level": 1, "duration_us": 500}
