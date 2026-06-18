"""Scheduler behavior tests."""
from __future__ import annotations

import asyncio

import pytest

from app.src.models import AppEvent, DeliveryMode, EventSource, EventSubscription, FeatureContext, FeatureSpec
from app.src.scheduler import AppScheduler


class DummyPlatform:
    async def noop(self) -> None:
        return None


@pytest.mark.asyncio
async def test_dedupe_subscription_skips_reentrant_events() -> None:
    calls: list[str] = []
    gate = asyncio.Event()

    async def handler(context: FeatureContext) -> None:
        calls.append(context.activation.payload["id"])
        await gate.wait()

    scheduler = AppScheduler(DummyPlatform())
    scheduler.register_feature(
        FeatureSpec(
            name="dedupe_feature",
            subscriptions=[EventSubscription("evt", delivery_mode=DeliveryMode.DEDUPE, source=EventSource.INTERNAL, handler=handler)],
        )
    )
    await scheduler.start()

    await scheduler.emit(AppEvent("evt", EventSource.INTERNAL, {"id": "first"}))
    await asyncio.sleep(0.05)
    await scheduler.emit(AppEvent("evt", EventSource.INTERNAL, {"id": "second"}))
    await asyncio.sleep(0.05)
    gate.set()
    await asyncio.sleep(0.05)
    await scheduler.stop()

    assert calls == ["first"]


@pytest.mark.asyncio
async def test_queue_subscription_buffers_reentrant_events() -> None:
    calls: list[str] = []
    gate = asyncio.Event()

    async def handler(context: FeatureContext) -> None:
        calls.append(context.activation.payload["id"])
        if context.activation.payload["id"] == "first":
            await gate.wait()

    scheduler = AppScheduler(DummyPlatform())
    scheduler.register_feature(
        FeatureSpec(
            name="queue_feature",
            subscriptions=[EventSubscription("evt", delivery_mode=DeliveryMode.QUEUE, source=EventSource.INTERNAL, handler=handler)],
        )
    )
    await scheduler.start()

    await scheduler.emit(AppEvent("evt", EventSource.INTERNAL, {"id": "first"}))
    await asyncio.sleep(0.05)
    await scheduler.emit(AppEvent("evt", EventSource.INTERNAL, {"id": "second"}))
    await asyncio.sleep(0.05)
    gate.set()
    await asyncio.sleep(0.1)
    await scheduler.stop()

    assert calls == ["first", "second"]


@pytest.mark.asyncio
async def test_feature_can_publish_event_for_other_subscribers() -> None:
    calls: list[tuple[str, str]] = []

    async def source_handler(context: FeatureContext) -> None:
        calls.append((context.feature_name, context.activation.event_type))
        await context.emit_event("evt.target", {"from": "source_feature"})

    async def target_handler(context: FeatureContext) -> None:
        calls.append((context.feature_name, context.activation.event_type))

    scheduler = AppScheduler(DummyPlatform())
    scheduler.register_feature(
        FeatureSpec(
            name="source_feature",
            subscriptions=[EventSubscription.internal("evt.source", delivery_mode=DeliveryMode.QUEUE, handler=source_handler)],
        )
    )
    scheduler.register_feature(
        FeatureSpec(
            name="target_feature",
            subscriptions=[EventSubscription.internal("evt.target", delivery_mode=DeliveryMode.QUEUE, handler=target_handler)],
        )
    )
    await scheduler.start()
    await scheduler.emit(AppEvent("evt.source", EventSource.INTERNAL, {}))
    await asyncio.sleep(0.1)
    await scheduler.stop()

    assert calls == [("source_feature", "evt.source"), ("target_feature", "evt.target")]


@pytest.mark.asyncio
async def test_feature_must_not_publish_event_subscribed_by_itself() -> None:
    async def source_handler(context: FeatureContext) -> None:
        await context.emit_event("evt.source", {})

    scheduler = AppScheduler(DummyPlatform())
    scheduler.register_feature(
        FeatureSpec(
            name="self_feature",
            subscriptions=[EventSubscription.internal("evt.source", delivery_mode=DeliveryMode.QUEUE, handler=source_handler)],
        )
    )
    await scheduler.start()

    with pytest.raises(AssertionError, match="subscribed by itself"):
        await scheduler.emit_from_feature(
            source_feature="self_feature",
            event_type="evt.source",
            payload={},
        )

    await scheduler.stop()


@pytest.mark.asyncio
async def test_per_subscription_handlers_route_by_event_type() -> None:
    seen: list[tuple[str, str]] = []

    async def on_a(context: FeatureContext) -> None:
        seen.append(("a", context.activation.event_type))

    async def on_b(context: FeatureContext) -> None:
        seen.append(("b", context.activation.event_type))

    scheduler = AppScheduler(DummyPlatform())
    scheduler.register_feature(
        FeatureSpec(
            name="multi_handler",
            subscriptions=[
                EventSubscription("evt.a", source=EventSource.INTERNAL, handler=on_a),
                EventSubscription("evt.b", source=EventSource.INTERNAL, handler=on_b),
            ],
        )
    )
    await scheduler.start()
    await scheduler.emit(AppEvent("evt.a", EventSource.INTERNAL, {}))
    await scheduler.emit(AppEvent("evt.b", EventSource.INTERNAL, {}))
    await asyncio.sleep(0.1)
    await scheduler.stop()

    assert seen == [("a", "evt.a"), ("b", "evt.b")]


def test_subscription_without_handler_is_rejected() -> None:
    with pytest.raises(ValueError, match="handler"):
        FeatureSpec(
            name="no_handler",
            subscriptions=[EventSubscription("evt.x", source=EventSource.INTERNAL)],
        )

