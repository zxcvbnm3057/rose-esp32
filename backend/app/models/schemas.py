"""Pydantic schemas for API request/response models."""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Generic response ──────────────────────────────────────────
class ApiResponse(BaseModel):
    success: bool
    data: Any = None
    error: Optional[str] = None
    timestamp: float = 0.0


# ── GPIO ──────────────────────────────────────────────────────
class GpioConfigRequest(BaseModel):
    mode: int = Field(..., ge=0, le=4, description="0=INPUT 1=OUTPUT 2=INTERRUPT 3=ADC 4=SIGNAL")
    pull: int = Field(default=0, ge=0, le=2, description="0=NONE 1=DOWN 2=UP")
    edge: int = Field(default=0, ge=0, le=3)


class GpioSetRequest(BaseModel):
    value: int = Field(..., ge=0, le=1)


class AdcSampleRequest(BaseModel):
    samples: int = Field(default=1, ge=1, le=16)


class SignalEdge(BaseModel):
    level: int = Field(..., ge=0, le=1)
    duration_us: int = Field(..., ge=1, le=1_000_000)


class SignalTxRequest(BaseModel):
    signal: list[SignalEdge] = Field(..., max_length=256)
    delay_us: int = Field(default=0, ge=0)


class SignalRxRequest(BaseModel):
    timeout_us: int = Field(default=1_000_000, ge=1)
    max_edges: int = Field(default=100, ge=1, le=256)
    # Software glitch-merge resolution: preset name ("exact"/"fine"/"normal"/
    # "coarse") or microseconds (int). None == "exact" (keep every edge).
    resolution: int | str | None = Field(default=None)


class SignalExchangeRequest(BaseModel):
    tx_signal: list[SignalEdge] = Field(..., max_length=256)
    delay_us: int = Field(default=0, ge=0)
    rx_total_us: int = Field(default=500_000, ge=1)
    rx_max_edges: int = Field(default=100, ge=1, le=256)
    # Software glitch-merge resolution (preset name or microseconds). The
    # firmware always captures at finest resolution; merging happens in the
    # bridge client.  None == "exact".
    resolution: int | str | None = Field(default=None)


# ── UART ──────────────────────────────────────────────────────
class UartConfigRequest(BaseModel):
    baudrate: int = Field(..., ge=300)
    data_bits: int = Field(default=8, ge=5, le=8)
    parity: int = Field(default=0, ge=0, le=2)
    stop_bits: int = Field(default=1, ge=1, le=2)
    tx_gpio: int = Field(default=1)
    rx_gpio: int = Field(default=3)


class UartSendRequest(BaseModel):
    data: Optional[str] = None
    data_base64: Optional[str] = None
    encoding: str = "utf-8"


# ── Port ──────────────────────────────────────────────────────
class PortBindRequest(BaseModel):
    resource_type: int = Field(..., ge=0, le=1, description="0=GPIO 1=UART")
    id: int = Field(...)
    owner_id: int = Field(default=0)


class PortUnbindRequest(BaseModel):
    resource_type: int = Field(..., ge=0, le=1)
    id: int = Field(...)


# ── BLE ───────────────────────────────────────────────────────
class BlePairingEnableRequest(BaseModel):
    timeout_s: int = Field(default=60, ge=1)


class BleScanStartRequest(BaseModel):
    interval_s: int = Field(default=5, ge=1)


# ── System ────────────────────────────────────────────────────
class SyncConfirmRequest(BaseModel):
    correlation_id: int
    stage: int = Field(default=0, ge=0)


# ── Thread ────────────────────────────────────────────────────
class ThreadPassthroughRequest(BaseModel):
    device_id: int
    correlation_id: int = 0
    payload: str  # base64-encoded


# ── Custom Command ────────────────────────────────────────────
class CustomCmdStep(BaseModel):
    step_type: str
    config: dict[str, Any] = {}
    delay_ms: int = 0
    on_error: str = "abort"


class CustomCmdCreate(BaseModel):
    slug: str
    name: str
    description: str = ""
    steps: list[CustomCmdStep]


class CustomCmdUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    steps: Optional[list[CustomCmdStep]] = None
    enabled: Optional[bool] = None


class CustomCmdExecuteRequest(BaseModel):
    params: dict[str, Any] = {}
