"""Dynamic POST-only HTTP trigger surface declared by feature specs."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .models import EventSource, EventSubscription, FeatureSpec
from .scheduler import AppScheduler


def create_http_router(feature_specs: list[FeatureSpec]) -> APIRouter:
    router = APIRouter(prefix="/app", tags=["app"])

    @router.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        scheduler: AppScheduler = request.app.state.scheduler
        return {
            "ok": True,
            "features": sorted(scheduler.features().keys()),
            "cached_events": sorted(scheduler._event_cache.keys()),
            "http_triggers": _describe_http_triggers(feature_specs),
        }

    for spec in feature_specs:
        for subscription in spec.subscriptions:
            if subscription.source == EventSource.HTTP_TRIGGER:
                _add_post_trigger(router, spec, subscription)

    return router


def _describe_http_triggers(feature_specs: list[FeatureSpec]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for spec in feature_specs:
        for trigger in spec.subscriptions:
            if trigger.source != EventSource.HTTP_TRIGGER:
                continue
            items.append(
                {
                    "feature": spec.name,
                    "method": "POST",
                    "url": f"/app{trigger.path}",
                    "description": trigger.description,
                    "schema": trigger.request_model.model_json_schema() if trigger.request_model else {},
                }
            )
    return items


def _add_post_trigger(router: APIRouter, spec: FeatureSpec, trigger: EventSubscription) -> None:
    async def endpoint(request: Request) -> JSONResponse:
        scheduler: AppScheduler = request.app.state.scheduler
        try:
            raw_payload = await request.json()
            assert trigger.request_model is not None
            model = trigger.request_model.model_validate(raw_payload)
        except Exception as exc:
            return JSONResponse(
                status_code=503,
                content={"success": False, "error": f"invalid parameters: {exc}", "data": None},
            )
        assert trigger.path is not None
        await scheduler.emit_http(spec.name, trigger.event_type, model.model_dump())
        return JSONResponse(
            status_code=200,
            content={"success": True, "data": {"accepted": True, "feature": spec.name, "path": trigger.path}},
        )

    assert trigger.path is not None
    endpoint.__name__ = f"post_{spec.name}_{trigger.path.strip('/').replace('/', '_').replace('-', '_')}"
    router.add_api_route(
        trigger.path,
        endpoint,
        methods=["POST"],
        name=endpoint.__name__,
        description=trigger.description,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError | ValidationError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"success": False, "error": str(exc), "data": None})
