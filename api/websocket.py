"""
api/websocket.py - Real-Time WebSocket Telemetry Streaming Service for AeroPulse.
Manages persistent client connections, pushes initial snapshots, and broadcasts periodic telemetry updates.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from core.cache import AircraftCache
from models.schemas import TelemetryResponse

logger = logging.getLogger("aeropulse.websocket")

router = APIRouter()


class ConnectionManager:
    """
    Thread-safe and asyncio-safe connection manager for WebSocket telemetry clients.
    Tracks active client connections, dispatches broadcast messages, and prunes dead sockets.
    """

    def __init__(self) -> None:
        self._connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        """Returns the number of currently active WebSocket connections."""
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        """Accepts a new incoming WebSocket connection and registers it in the active pool."""
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)
        logger.info("WebSocket client connected. Total active: %d", self.active_count)

    async def disconnect(self, websocket: WebSocket) -> None:
        """Removes a disconnected WebSocket from the active connection pool."""
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)
        logger.info("WebSocket client disconnected. Total active: %d", self.active_count)

    async def send_personal_message(self, message: Dict[str, Any], websocket: WebSocket) -> bool:
        """Sends a JSON message to a single specific client."""
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json(message)
                return True
        except Exception as exc:
            logger.debug("Failed sending personal message to WebSocket: %s", exc)
        return False

    async def broadcast(self, message: Dict[str, Any]) -> int:
        """
        Broadcasts a JSON payload to all active connections.
        Safely prunes any connections that have disconnected or failed during sending.
        """
        async with self._lock:
            targets = list(self._connections)

        if not targets:
            return 0

        dead_sockets: List[WebSocket] = []
        sent_count = 0

        for ws in targets:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json(message)
                    sent_count += 1
                else:
                    dead_sockets.append(ws)
            except (WebSocketDisconnect, RuntimeError, Exception) as exc:
                logger.debug("Failed broadcasting to WebSocket client, marking for eviction: %s", exc)
                dead_sockets.append(ws)

        if dead_sockets:
            async with self._lock:
                for ws in dead_sockets:
                    if ws in self._connections:
                        self._connections.remove(ws)
            logger.info("Evicted %d dead WebSocket connections. Active remaining: %d", len(dead_sockets), self.active_count)

        return sent_count

    async def broadcast_shutdown(self) -> None:
        """Sends a shutdown notification to all clients and gracefully closes connections."""
        shutdown_msg = {
            "event": "SHUTDOWN",
            "type": "SHUTDOWN",
            "message": "AeroPulse server is shutting down",
            "timestamp": time.time(),
        }
        async with self._lock:
            targets = list(self._connections)
            self._connections.clear()

        for ws in targets:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json(shutdown_msg)
                    await ws.close(code=1000, reason="Server shutdown")
            except Exception:
                pass


# Global singleton manager instance
manager = ConnectionManager()


def build_telemetry_snapshot(cache: AircraftCache) -> Dict[str, Any]:
    """Helper to construct a serialized TelemetryResponse payload from the cache."""
    flights = cache.get_all_active(airborne_only=False)
    airborne = [f for f in flights if not f.on_ground]
    anomalous = [f for f in flights if f.has_anomaly or f.status != "NOMINAL"]

    resp = TelemetryResponse(
        timestamp=time.time(),
        total_aircraft=len(flights),
        airborne_count=len(airborne),
        anomaly_count=len(anomalous),
        aircraft=flights,
    )
    return resp.model_dump(mode="json")


@router.websocket("/telemetry")
async def websocket_telemetry_endpoint(websocket: WebSocket) -> None:
    """
    WebSocket endpoint at /ws/telemetry.
    - Pushes initial 'SNAPSHOT' payload upon connection.
    - Listens for client messages (handles 'PING' -> 'PONG').
    - Receives broadcast 'UPDATE' payloads from background broadcaster.
    - Gracefully handles disconnection without unhandled exceptions.
    """
    await manager.connect(websocket)

    # 1. Dispatch initial SNAPSHOT payload
    try:
        cache: Optional[AircraftCache] = getattr(websocket.app.state, "cache", None)
        if cache is not None:
            snapshot_data = build_telemetry_snapshot(cache)
        else:
            snapshot_data = {
                "timestamp": time.time(),
                "total_aircraft": 0,
                "airborne_count": 0,
                "anomaly_count": 0,
                "aircraft": [],
                "flights": [],
            }

        await websocket.send_json({
            "event": "SNAPSHOT",
            "type": "SNAPSHOT",
            "data": snapshot_data,
            "timestamp": time.time(),
        })

        # 2. Client message processing loop (ping-pong & client heartbeats)
        while True:
            raw_text = await websocket.receive_text()
            # Parse possible ping formats (plain string "PING" or JSON {"type": "PING"})
            is_ping = False
            try:
                parsed = json.loads(raw_text)
                if isinstance(parsed, dict):
                    msg_type = str(parsed.get("type") or parsed.get("event") or "").upper()
                    if msg_type == "PING":
                        is_ping = True
                elif isinstance(parsed, str) and parsed.strip().upper() == "PING":
                    is_ping = True
            except Exception:
                if raw_text.strip().upper() == "PING":
                    is_ping = True

            if is_ping:
                await websocket.send_json({
                    "event": "PONG",
                    "type": "PONG",
                    "timestamp": time.time(),
                })

    except WebSocketDisconnect:
        logger.debug("Client initiated WebSocketDisconnect")
    except Exception as exc:
        logger.debug("WebSocket connection closed with: %s", exc)
    finally:
        await manager.disconnect(websocket)


async def telemetry_broadcast_loop(
    cache: AircraftCache,
    conn_manager: ConnectionManager,
    interval_seconds: float = 2.0,
    shutdown_event: Optional[asyncio.Event] = None,
) -> None:
    """
    Background worker task that periodically broadcasts telemetry updates
    to all active WebSocket clients.
    """
    logger.info("WebSocket telemetry broadcast loop started (interval=%.1fs).", interval_seconds)
    try:
        while True:
            if shutdown_event is not None and shutdown_event.is_set():
                break

            await asyncio.sleep(interval_seconds)

            if conn_manager.active_count > 0:
                try:
                    snapshot = build_telemetry_snapshot(cache)
                    await conn_manager.broadcast({
                        "event": "UPDATE",
                        "type": "UPDATE",
                        "data": snapshot,
                        "timestamp": time.time(),
                    })
                except Exception as b_exc:
                    logger.debug("Error during periodic WebSocket broadcast: %s", b_exc)

    except asyncio.CancelledError:
        logger.info("WebSocket telemetry broadcast loop cancelled.")
    finally:
        logger.info("WebSocket telemetry broadcast loop terminated.")
