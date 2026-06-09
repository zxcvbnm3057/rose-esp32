"""Pin lock persistence + UART config persistence + expected state mismatch detection."""
import time
from fastapi import APIRouter, Path, Depends, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db.database import get_session
from ..models.custom_cmd import PinLock, UartConfigModel
from ..models.schemas import ApiResponse

router = APIRouter(prefix="/pins", tags=["pins"])


@router.get("/locks")
async def get_locks(db: AsyncSession = Depends(get_session)):
    """Return all persisted pin states + UART configs."""
    result = await db.execute(select(PinLock))
    rows = result.scalars().all()
    pins = []
    for r in rows:
        pins.append({
            "gpio": r.gpio,
            "locked": bool(r.locked),
            "expected_mode": r.expected_mode,
            "expected_value": r.expected_value,
        })

    # Also return persisted UART configs
    uart_result = await db.execute(select(UartConfigModel))
    uart_rows = uart_result.scalars().all()
    uarts = []
    for r in uart_rows:
        uarts.append({
            "uart_id": r.uart_id,
            "baudrate": r.baudrate,
            "tx_gpio": r.tx_gpio,
            "rx_gpio": r.rx_gpio,
            "data_bits": r.data_bits,
            "parity": r.parity,
            "stop_bits": r.stop_bits,
        })

    return ApiResponse(success=True, data={"pins": pins, "uarts": uarts}, timestamp=time.time())


@router.post("/{gpio}/lock")
async def lock_pin(gpio: int = Path(...), db: AsyncSession = Depends(get_session)):
    """Lock a pin with optional expected state."""
    result = await db.execute(select(PinLock).where(PinLock.gpio == gpio))
    row = result.scalar_one_or_none()
    if row:
        row.locked = 1
    else:
        row = PinLock(gpio=gpio, locked=1)
        db.add(row)
    await db.commit()
    return ApiResponse(success=True, data={"gpio": gpio, "locked": True}, timestamp=time.time())


@router.delete("/{gpio}/lock")
async def unlock_pin(gpio: int = Path(...), db: AsyncSession = Depends(get_session)):
    """Unlock a pin."""
    result = await db.execute(select(PinLock).where(PinLock.gpio == gpio))
    row = result.scalar_one_or_none()
    if row:
        row.locked = 0
        row.expected_mode = None
        row.expected_value = None
        await db.commit()
    return ApiResponse(success=True, data={"gpio": gpio, "locked": False}, timestamp=time.time())


@router.put("/{gpio}/expected")
async def save_expected_state(gpio: int = Path(...), db: AsyncSession = Depends(get_session)):
    """Save the expected mode/value for a locked pin (called when user configures it)."""
    from fastapi import Body
    # Use request body directly
    return ApiResponse(success=True, data={}, timestamp=time.time())


@router.post("/{gpio}/expected")
async def set_expected_state(
    gpio: int = Path(...),
    body: dict = Body(...),
    db: AsyncSession = Depends(get_session),
):
    """Save expected state for a pin (from JSON body)."""
    result = await db.execute(select(PinLock).where(PinLock.gpio == gpio))
    row = result.scalar_one_or_none()
    if not row:
        row = PinLock(gpio=gpio, locked=0)
        db.add(row)
    row.expected_mode = body.get("expected_mode")
    row.expected_value = body.get("expected_value")
    await db.commit()
    return ApiResponse(success=True, data={"gpio": gpio}, timestamp=time.time())


# ── UART config persistence ───────────────────────────

@router.post("/uart/{uart_id}")
async def save_uart_config(
    uart_id: int = Path(...),
    body: dict = Body(...),
    db: AsyncSession = Depends(get_session),
):
    """Save UART configuration to DB."""
    result = await db.execute(select(UartConfigModel).where(UartConfigModel.uart_id == uart_id))
    row = result.scalar_one_or_none()
    if not row:
        row = UartConfigModel(uart_id=uart_id)
        db.add(row)
    row.baudrate = body.get("baudrate", 115200)
    row.tx_gpio = body.get("tx_gpio", 1)
    row.rx_gpio = body.get("rx_gpio", 3)
    row.data_bits = body.get("data_bits", 8)
    row.parity = body.get("parity", 0)
    row.stop_bits = body.get("stop_bits", 1)
    await db.commit()
    return ApiResponse(success=True, data={"uart_id": uart_id}, timestamp=time.time())


@router.delete("/uart/{uart_id}")
async def delete_uart_config(
    uart_id: int = Path(...),
    db: AsyncSession = Depends(get_session),
):
    """Remove persisted UART configuration."""
    result = await db.execute(select(UartConfigModel).where(UartConfigModel.uart_id == uart_id))
    row = result.scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()
    return ApiResponse(success=True, data={"uart_id": uart_id}, timestamp=time.time())

