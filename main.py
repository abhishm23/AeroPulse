"""
main.py - AeroPulse Backend Application Entry Point.
Configures FastAPI application, lifespan context manager for background ingestion,
attaches REST and WebSocket routers, and mounts static assets at root.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import router as api_router
from api.websocket import router as ws_router, manager as ws_manager, telemetry_broadcast_loop
from core.cache import AircraftCache
from core.ingestion import OpenSkyIngestionWorker
from core.synthetic import SyntheticReplayGenerator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("aeropulse.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Modern FastAPI lifespan context manager.
    Manages background ingestion worker and WebSocket broadcasting task lifecycle:
    - Starts the background ingestion task on startup.
    - Gracefully cancels, stops, and awaits cleanup on shutdown.
    """
    logger.info("Initializing AeroPulse server lifespan...")

    # 1. Initialize core state if not already present
    if not hasattr(app.state, "cache") or app.state.cache is None:
        app.state.cache = AircraftCache(max_trail_points=30)
    if not hasattr(app.state, "ws_manager") or app.state.ws_manager is None:
        app.state.ws_manager = ws_manager
    if not hasattr(app.state, "synthetic_gen") or app.state.synthetic_gen is None:
        app.state.synthetic_gen = SyntheticReplayGenerator(seed=42)

    # Pre-seed cache if empty to guarantee instant availability
    if len(app.state.cache.get_all_active()) == 0:
        initial_states = app.state.synthetic_gen.tick()
        for st in initial_states:
            app.state.cache.update_vector(st)

    # 2. Configure Ingestion Worker
    force_mock = (
        os.getenv("AEROPULSE_MODE", "").upper() == "REPLAY"
        or os.getenv("AEROPULSE_FORCE_MOCK", "0").lower() in ("1", "true", "yes")
    )
    worker = OpenSkyIngestionWorker(
        cache=app.state.cache,
        synthetic_generator=app.state.synthetic_gen,
        force_mock=force_mock,
        fallback_enabled=True,
    )
    app.state.worker = worker
    app.state.ingestion_worker = worker

    # 3. Launch background ingestion worker
    ingestion_task = worker.start()
    app.state.ingestion_task = ingestion_task

    # 4. Launch background WebSocket telemetry broadcaster
    broadcast_task = asyncio.create_task(
        telemetry_broadcast_loop(
            cache=app.state.cache,
            conn_manager=app.state.ws_manager,
            interval_seconds=2.0,
        ),
        name="aeropulse_websocket_broadcaster",
    )
    app.state.broadcast_task = broadcast_task

    logger.info("AeroPulse server initialization complete. Serving requests.")
    try:
        yield
    finally:
        logger.info("Initiating AeroPulse server graceful shutdown...")

        # 1. Cancel and await WebSocket broadcast task
        if broadcast_task and not broadcast_task.done():
            broadcast_task.cancel()
            try:
                await broadcast_task
            except (asyncio.CancelledError, Exception):
                pass

        # 2. Stop Ingestion Worker and cancel worker task
        await worker.stop()
        if ingestion_task and not ingestion_task.done():
            ingestion_task.cancel()
            try:
                await ingestion_task
            except (asyncio.CancelledError, Exception):
                pass

        # 3. Gracefully notify and close active WebSocket clients
        await app.state.ws_manager.broadcast_shutdown()

        # 4. Close HTTP client session
        await worker.close()
        logger.info("AeroPulse server shutdown finalized cleanly.")


# ============================================================================
# FASTAPI APPLICATION INSTANCE
# ============================================================================

app = FastAPI(
    title="AeroPulse",
    description="High-throughput mechanical flight anomaly detection engine & military HUD dark-mode dashboard",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for local development and browser cross-origin safety
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------------------------------------------------------
# Baseline State Initialization (for immediate TestClient compatibility)
# ----------------------------------------------------------------------------
default_cache = AircraftCache(max_trail_points=30)
default_synthetic_gen = SyntheticReplayGenerator(seed=42)

# Populate initial snapshot with deterministic synthetic replay vectors
initial_vectors = default_synthetic_gen.tick()
for vec in initial_vectors:
    default_cache.update_vector(vec)

default_worker = OpenSkyIngestionWorker(
    cache=default_cache,
    synthetic_generator=default_synthetic_gen,
    force_mock=False,
    fallback_enabled=True,
)

app.state.cache = default_cache
app.state.synthetic_gen = default_synthetic_gen
app.state.worker = default_worker
app.state.ingestion_worker = default_worker
app.state.ws_manager = ws_manager

# ----------------------------------------------------------------------------
# Route Registration: API and WebSocket routers MUST be attached FIRST
# ----------------------------------------------------------------------------
app.include_router(api_router, prefix="/api")
app.include_router(ws_router, prefix="/ws")

# ----------------------------------------------------------------------------
# Static File Mounting: Attached AFTER API routers to prevent route collisions
# ----------------------------------------------------------------------------
static_dir = Path(__file__).resolve().parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
index_file = static_dir / "index.html"
if not index_file.is_file():
    index_file.write_text("<!DOCTYPE html><h1>AeroPulse</h1>", encoding="utf-8")

app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
