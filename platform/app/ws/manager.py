"""WebSocket connection manager — multi-client mode with per-connection roles."""
from __future__ import annotations
import asyncio
import logging
from typing import Any
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages multiple WebSocket connections.

    Each connection has a logical role:
      - ``console``: hardware operator UI, allowed to issue control commands
      - ``app``: business backend, read-only (subscribe / read data only)

    Broadcasting is fan-out to all connected clients.
    """

    def __init__(self):
        self._clients: dict[WebSocket, str] = {}
        self._lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        return len(self._clients)

    async def connect(self, ws: WebSocket, role: str = "console"):
        """Accept a new WebSocket and register its role."""
        async with self._lock:
            await ws.accept()
            self._clients[ws] = role
            logger.info("WS connected role=%s active=%d", role, len(self._clients))

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            role = self._clients.pop(ws, None)
            if role is not None:
                logger.info("WS disconnected role=%s active=%d", role, len(self._clients))

    def role_of(self, ws: WebSocket) -> str | None:
        return self._clients.get(ws)

    async def broadcast(self, data: dict[str, Any]):
        """Broadcast JSON to all connected clients."""
        if not self._clients:
            return
        # Snapshot to avoid mutation during iteration.
        for ws in list(self._clients.keys()):
            try:
                await ws.send_json(data)
            except Exception:
                await self.disconnect(ws)

    async def broadcast_event(self, event: dict[str, Any]):
        await self.broadcast(event)


# Singleton
manager = ConnectionManager()
