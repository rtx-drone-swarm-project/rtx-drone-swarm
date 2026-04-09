"""WebSocket connection tracking and broadcast helpers."""

import json
from typing import List

from fastapi import WebSocket


class ConnectionManager:
    """Tracks active WebSocket clients and broadcasts JSON messages to them."""

    def __init__(self):
        """Initialize the in-memory list of active WebSocket connections."""
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accept a socket and register it for future broadcasts."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """Remove a socket from the active connection set if it is still tracked."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Send a JSON-encoded message to all connected clients and prune dead sockets."""
        dead = []
        for conn in self.active_connections:
            try:
                await conn.send_text(json.dumps(message))
            except Exception:
                dead.append(conn)
        for conn in dead:
            self.disconnect(conn)


manager = ConnectionManager()
