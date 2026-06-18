"""Application bootstrap."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from .config import settings
from .feature_loader import discover_features
from .http_api import create_http_router, validation_exception_handler
from .platform_sdk import PlatformClient
from .scheduler import AppScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    platform = PlatformClient()
    scheduler = AppScheduler(platform)
    feature_specs = discover_features()

    for spec in feature_specs:
        scheduler.register_feature(spec)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.scheduler = scheduler
        app.state.platform = platform
        await scheduler.start()
        await platform.start_ws_listener(scheduler.emit)
        logger.info("Business app started on %s:%s", settings.host, settings.port)
        try:
            yield
        finally:
            await platform.stop()
            await scheduler.stop()
            logger.info("Business app stopped")

    app = FastAPI(title="Rose Business App", version="1.0.0", lifespan=lifespan)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(ValidationError, validation_exception_handler)
    app.include_router(create_http_router(feature_specs))
    return app


app = create_app()
