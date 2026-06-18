"""Event scheduler and feature-thread orchestration.

Model
-----
- A single dispatcher coroutine drains one event queue, caches the latest
  event per type, and fans out activations to feature workers.
- Each feature is one worker coroutine that blocks on its mailbox until the
  dispatcher hands it an activation it subscribed to.
- A busy feature treats new activations per its declared DeliveryMode:
  DEDUPE drops them, QUEUE buffers them for after the current run.

Event sources
-------------
1. platform_ws  — events relayed from the platform websocket.
2. timer        — cron subscriptions declared by features.
3. http_trigger — manual POSTs routed through per-feature HTTP endpoints.

Timer and HTTP subscriptions are both represented as normal event
subscriptions with different ``source`` values.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .config import settings
from .cron import CronExpr
from .models import AppEvent, DeliveryMode, EventSource, FeatureContext, FeatureSpec

logger = logging.getLogger(__name__)

@dataclass(slots=True)
class FeatureRuntime:
    spec: FeatureSpec
    mailbox: asyncio.Queue[AppEvent] = field(default_factory=asyncio.Queue)
    is_running: bool = False
    pending: deque[AppEvent] = field(default_factory=deque)
    worker_task: asyncio.Task[None] | None = None


class AppScheduler:
    def __init__(self, platform: Any) -> None:
        self._platform = platform
        self._event_queue: asyncio.Queue[AppEvent] = asyncio.Queue(maxsize=settings.scheduler_queue_size)
        self._features: dict[str, FeatureRuntime] = {}
        # event_type -> list of (feature_name, delivery_mode)
        self._subscriptions: dict[str, list[tuple[str, DeliveryMode]]] = defaultdict(list)
        self._event_cache: dict[str, AppEvent] = {}
        self._dispatcher_task: asyncio.Task[None] | None = None
        self._timer_tasks: list[asyncio.Task[None]] = []
        self._running = False

    # ── lifecycle ─────────────────────────────────────────────
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        for runtime in self._features.values():
            runtime.worker_task = asyncio.create_task(self._feature_loop(runtime))
        self._dispatcher_task = asyncio.create_task(self._dispatch_loop())
        # Launch timer subscriptions now that the loop is running.
        for runtime in self._features.values():
            for subscription in runtime.spec.subscriptions:
                if subscription.source == EventSource.TIMER:
                    self._timer_tasks.append(
                        asyncio.create_task(
                            self._cron_loop(
                                event_type=subscription.event_type,
                                expression=subscription.cron or "",
                                payload=subscription.payload,
                            )
                        )
                    )

    async def stop(self) -> None:
        self._running = False
        for task in self._timer_tasks:
            task.cancel()
        if self._dispatcher_task:
            self._dispatcher_task.cancel()
            try:
                await self._dispatcher_task
            except asyncio.CancelledError:
                pass
        for runtime in self._features.values():
            if runtime.worker_task:
                runtime.worker_task.cancel()
        for runtime in self._features.values():
            if runtime.worker_task:
                try:
                    await runtime.worker_task
                except asyncio.CancelledError:
                    pass

    # ── registration ──────────────────────────────────────────
    def register_feature(self, spec: FeatureSpec) -> None:
        if not spec.enabled:
            logger.info("Skip disabled feature: %s", spec.name)
            return
        if spec.name in self._features:
            raise ValueError(f"Feature already registered: {spec.name}")
        runtime = FeatureRuntime(spec=spec)
        self._features[spec.name] = runtime

        for subscription in spec.subscriptions:
            self._subscriptions[subscription.event_type].append((spec.name, subscription.delivery_mode))

    def features(self) -> dict[str, FeatureRuntime]:
        return self._features

    # ── emit / cache ──────────────────────────────────────────
    async def emit(self, event: AppEvent) -> None:
        await self._event_queue.put(event)

    def latest_event(self, event_type: str) -> AppEvent | None:
        return self._event_cache.get(event_type)

    async def emit_http(self, feature_name: str, event_type: str, payload: dict[str, Any]) -> None:
        await self.emit(
            AppEvent(
                event_type=event_type,
                source=EventSource.HTTP_TRIGGER,
                payload=payload,
            )
        )

    async def emit_from_feature(
        self,
        *,
        source_feature: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        subscriptions = self._subscriptions.get(event_type, [])
        assert all(feature_name != source_feature for feature_name, _ in subscriptions), (
            "feature must not publish an event subscribed by itself"
        )
        await self.emit(
            AppEvent(
                event_type=event_type,
                source=EventSource.INTERNAL,
                payload=payload,
            )
        )

    # ── timers ────────────────────────────────────────────────
    async def _cron_loop(self, event_type: str, expression: str, payload: dict[str, Any]) -> None:
        cron_expr = CronExpr(expression)
        while self._running:
            now = datetime.now()
            nxt = cron_expr.next_after(now)
            delay = (nxt - now).total_seconds()
            try:
                await asyncio.sleep(max(delay, 0))
            except asyncio.CancelledError:
                return
            await self.emit(AppEvent(event_type=event_type, source=EventSource.TIMER, payload=payload))

    # ── dispatch / worker ─────────────────────────────────────
    async def _dispatch_loop(self) -> None:
        while self._running:
            event = await self._event_queue.get()
            self._event_cache[event.event_type] = event
            for feature_name, delivery_mode in self._subscriptions.get(event.event_type, []):
                runtime = self._features[feature_name]
                if runtime.is_running:
                    if delivery_mode == DeliveryMode.DEDUPE:
                        continue
                    runtime.pending.append(event)
                    continue
                await runtime.mailbox.put(event)

    async def _feature_loop(self, runtime: FeatureRuntime) -> None:
        while True:
            event = await runtime.mailbox.get()
            runtime.is_running = True
            try:
                context = FeatureContext(
                    feature_name=runtime.spec.name,
                    activation=event,
                    scheduler=self,
                    platform=self._platform,
                )
                await runtime.spec.handler(context)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Feature '%s' failed handling event '%s'",
                    runtime.spec.name,
                    event.event_type,
                )
            finally:
                runtime.is_running = False
                if runtime.pending:
                    await runtime.mailbox.put(runtime.pending.popleft())
