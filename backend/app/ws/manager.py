"""WebSocket connection manager — single-client mode."""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Any
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections — only ONE active client at a time."""

    def __init__(self):
        self._ws: WebSocket | None = None
        self._lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        return 1 if self._ws is not None else 0

    async def connect(self, ws: WebSocket):
        """Accept new WS, kick old one if any."""
        async with self._lock:
            # Kick existing
            if self._ws is not None:
                old = self._ws
                self._ws = None
                try:
                    await old.send_json({"type": "kicked", "reason": "new_connection"})
                    await old.close(code=4001)
                except Exception:
                    pass
                logger.info("Kicked old WS client for new connection")

            await ws.accept()
            self._ws = ws
            logger.info("WS connected (single client)")

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            if self._ws is ws:
                self._ws = None
                logger.info("WS disconnected")

    async def broadcast(self, data: dict[str, Any]):
        """Send JSON to the single client."""
        ws = self._ws
        if ws is None:
            return
        try:
            await ws.send_json(data)
        except Exception:
            await self.disconnect(ws)

    async def broadcast_event(self, event: dict[str, Any]):
        await self.broadcast(event)


# Singleton
manager = ConnectionManager()
