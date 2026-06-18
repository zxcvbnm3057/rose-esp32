"""Shared event and command models."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import time

from pydantic import BaseModel


class EventSource(str, Enum):
    PLATFORM_WS = "platform_ws"
    TIMER = "timer"
    HTTP_TRIGGER = "http_trigger"
    INTERNAL = "internal"


class DeliveryMode(str, Enum):
    DEDUPE = "dedupe"
    QUEUE = "queue"


@dataclass(slots=True)
class AppEvent:
    event_type: str
    source: EventSource
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class EventSubscription:
    event_type: str
    delivery_mode: DeliveryMode = DeliveryMode.DEDUPE
    source: EventSource = EventSource.PLATFORM_WS
    payload: dict[str, Any] = field(default_factory=dict)
    cron: str | None = None
    path: str | None = None
    request_model: type[BaseModel] | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if self.source == EventSource.TIMER and not self.cron:
            raise ValueError("timer subscription requires cron expression")
        if self.source != EventSource.TIMER and self.cron is not None:
            raise ValueError("only timer subscriptions may define cron")
        if self.source == EventSource.HTTP_TRIGGER:
            if not self.path or self.request_model is None:
                raise ValueError("http subscription requires path and request_model")

    @classmethod
    def platform(
        cls,
        event_type: str,
        delivery_mode: DeliveryMode = DeliveryMode.DEDUPE,
    ) -> EventSubscription:
        return cls(event_type=event_type, source=EventSource.PLATFORM_WS, delivery_mode=delivery_mode)

    @classmethod
    def internal(
        cls,
        event_type: str,
        delivery_mode: DeliveryMode = DeliveryMode.DEDUPE,
    ) -> EventSubscription:
        return cls(event_type=event_type, source=EventSource.INTERNAL, delivery_mode=delivery_mode)

    @classmethod
    def timer(
        cls,
        event_type: str,
        cron: str,
        *,
        delivery_mode: DeliveryMode = DeliveryMode.DEDUPE,
        payload: dict[str, Any] | None = None,
        description: str = "",
    ) -> EventSubscription:
        return cls(
            event_type=event_type,
            source=EventSource.TIMER,
            delivery_mode=delivery_mode,
            payload=payload or {},
            cron=cron,
            description=description,
        )

    @classmethod
    def http(
        cls,
        path: str,
        request_model: type[BaseModel],
        *,
        event_type: str | None = None,
        delivery_mode: DeliveryMode = DeliveryMode.QUEUE,
        description: str = "",
    ) -> EventSubscription:
        normalized = path.strip("/").replace("/", ".") or "root"
        return cls(
            event_type=event_type or f"http.{normalized}",
            source=EventSource.HTTP_TRIGGER,
            delivery_mode=delivery_mode,
            path=path,
            request_model=request_model,
            description=description,
        )


@dataclass(slots=True)
class FeatureContext:
    feature_name: str
    activation: AppEvent
    scheduler: Any
    platform: Any

    async def emit_event(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        await self.scheduler.emit_from_feature(
            source_feature=self.feature_name,
            event_type=event_type,
            payload=payload or {},
        )


FeatureHandler = Callable[[FeatureContext], Awaitable[None]]


@dataclass(slots=True)
class FeatureSpec:
    name: str
    handler: FeatureHandler
    enabled: bool = True
    subscriptions: list[EventSubscription] = field(default_factory=list)
