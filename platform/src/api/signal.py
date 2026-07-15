"""Signal endpoints (TX/RX/Exchange)."""
import time
from fastapi import APIRouter, Path, HTTPException
from ..config import get_capabilities
from ..services import bridge_service
from ..models.schemas import ApiResponse, SignalTxRequest, SignalRxRequest, SignalExchangeRequest
from .errors import check_connected, check_bridge_ok

router = APIRouter(prefix="/gpio", tags=["signal"])

MAX_SIGNAL_CARRIER_HZ = 500_000


def _validate_carrier(carrier_hz: int, duty_cycle: float) -> None:
    if carrier_hz < 0 or carrier_hz > MAX_SIGNAL_CARRIER_HZ:
        raise HTTPException(status_code=422, detail=f"carrier_hz must be between 0 and {MAX_SIGNAL_CARRIER_HZ}")
    if carrier_hz == 0:
        return
    if not (0.0 < duty_cycle <= 1.0):
        raise HTTPException(status_code=422, detail="duty_cycle must be in (0, 1]")


@router.post("/{gpio}/signal/tx")
async def signal_tx(gpio: int = Path(...), req: SignalTxRequest = None):
    if not get_capabilities().get("signal", False):
        raise HTTPException(status_code=501, detail="signal not supported on this hardware")
    check_connected()
    _validate_carrier(req.carrier_hz, req.duty_cycle)

    signal_list = [{"level": s.level, "duration_us": s.duration_us} for s in req.signal]
    ok = await bridge_service.signal_tx(
        gpio, signal_list, req.delay_us, req.carrier_hz, req.duty_cycle,
        req.repeat, req.repeat_gap_us,
    )
    check_bridge_ok(ok, "Signal TX failed")
    return ApiResponse(
        success=True,
        data={
            "gpio": gpio,
            "edges_sent": len(req.signal),
            "carrier_hz": req.carrier_hz,
            "duty_cycle": req.duty_cycle,
            "repeat": req.repeat,
            "repeat_gap_us": req.repeat_gap_us,
        },
        timestamp=time.time(),
    )


@router.post("/{gpio}/signal/rx")
async def signal_rx(gpio: int = Path(...), req: SignalRxRequest = None):
    if not get_capabilities().get("signal", False):
        raise HTTPException(status_code=501, detail="signal not supported")
    check_connected()

    result = await bridge_service.signal_rx(gpio, req.timeout_us, req.max_edges, req.resolution)
    check_bridge_ok(result, "Signal capture timed out or failed")
    return ApiResponse(success=True, data={
        "gpio": gpio, "edge_count": len(result),
        "edges": [{"level": lv, "duration_us": dur} for lv, dur in result],
    }, timestamp=time.time())


@router.post("/{gpio}/signal/exchange")
async def signal_exchange(gpio: int = Path(...), req: SignalExchangeRequest = None):
    if not get_capabilities().get("signal", False):
        raise HTTPException(status_code=501, detail="signal not supported")
    check_connected()
    _validate_carrier(req.carrier_hz, req.duty_cycle)

    tx_signal = [{"level": s.level, "duration_us": s.duration_us} for s in req.tx_signal]
    result = await bridge_service.signal_exchange(
        gpio,
        tx_signal,
        req.delay_us,
        req.rx_total_us,
        req.rx_max_edges,
        req.carrier_hz,
        req.duty_cycle,
        req.resolution,
    )
    check_bridge_ok(result, "Signal exchange failed or timed out")
    return ApiResponse(success=True, data={
        "gpio": gpio, "edge_count": len(result),
        "carrier_hz": req.carrier_hz,
        "duty_cycle": req.duty_cycle,
        "edges": [{"level": lv, "duration_us": dur} for lv, dur in result],
    }, timestamp=time.time())


@router.get("/signal/resolutions")
async def list_signal_resolutions():
    """List available signal-capture resolution presets (software glitch-merge).

    Resolution is applied in the bridge client, not the firmware: a pulse
    narrower than the chosen resolution is merged into the previous edge.
    Clients may also pass a raw integer (microseconds) instead of a preset.
    """
    from ..bridge import RESOLUTION_PRESETS
    return ApiResponse(success=True, data={
        "presets": [{"name": k, "resolution_us": v} for k, v in RESOLUTION_PRESETS.items()],
        "default": "exact",
    }, timestamp=time.time())
