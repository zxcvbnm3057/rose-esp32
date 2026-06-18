"""Application configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _get_env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass(frozen=True, slots=True)
class AppSettings:
    host: str = _get_env("ROSE_APP_HOST", "0.0.0.0")
    port: int = int(_get_env("ROSE_APP_PORT", "9000"))
    platform_base_url: str = _get_env("ROSE_APP_PLATFORM_BASE_URL", "http://127.0.0.1:8000")
    platform_ws_url: str = _get_env("ROSE_APP_PLATFORM_WS_URL", "ws://127.0.0.1:8000/ws")
    http_timeout_s: float = float(_get_env("ROSE_APP_HTTP_TIMEOUT_S", "10.0"))
    reconnect_delay_s: float = float(_get_env("ROSE_APP_RECONNECT_DELAY_S", "3.0"))
    scheduler_queue_size: int = int(_get_env("ROSE_APP_SCHEDULER_QUEUE_SIZE", "1024"))


settings = AppSettings()
