"""Signal endpoints (TX/RX/Exchange)."""
import time
from fastapi import APIRouter, Path, HTTPException
from ..config import get_capabilities
from ..services import bridge_service
from ..models.schemas import ApiResponse, SignalTxRequest, SignalRxRequest, SignalExchangeRequest
from .errors import check_connected, check_bridge_ok

router = APIRouter(prefix="/gpio", tags=["signal"])


@router.post("/{gpio}/signal/tx")
async def signal_tx(gpio: int = Path(...), req: SignalTxRequest = None):
    if not get_capabilities().get("signal", False):
        raise HTTPException(status_code=501, detail="signal not supported on this hardware")
    check_connected()

    signal_list = [{"level": s.level, "duration_us": s.duration_us} for s in req.signal]
    ok = await bridge_service.signal_tx(gpio, signal_list, req.delay_us)
    check_bridge_ok(ok, "Signal TX failed")
    return ApiResponse(success=True, data={"gpio": gpio, "edges_sent": len(req.signal)}, timestamp=time.time())


@router.post("/{gpio}/signal/rx")
async def signal_rx(gpio: int = Path(...), req: SignalRxRequest = None):
    if not get_capabilities().get("signal", False):
        raise HTTPException(status_code=501, detail="signal not supported")
    check_connected()

    result = await bridge_service.signal_rx(gpio, req.timeout_us, req.max_edges)
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

    tx_signal = [{"level": s.level, "duration_us": s.duration_us} for s in req.tx_signal]
    result = await bridge_service.signal_exchange(
        gpio, tx_signal, req.delay_us, req.rx_total_us, req.rx_max_edges, req.rx_resolution_us)
    check_bridge_ok(result, "Signal exchange failed or timed out")
    return ApiResponse(success=True, data={
        "gpio": gpio, "edge_count": len(result),
        "edges": [{"level": lv, "duration_us": dur} for lv, dur in result],
    }, timestamp=time.time())
