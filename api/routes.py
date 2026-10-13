"""
api/routes.py - FastAPI REST Endpoints for AeroPulse.
Implements the 5 authoritative REST endpoints:
- GET /api/telemetry
- GET /api/flight/{icao24}
- GET /api/anomalies
- GET /api/stats
- GET /api/health
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from core.cache import AircraftCache
from core.ingestion import OpenSkyIngestionWorker
from api.websocket import ConnectionManager, manager as default_ws_manager
from models.schemas import (
    AnomaliesResponse,
    CacheHealthStats,
    FlightDetailResponse,
    HealthResponse,
    SystemStatsResponse,
    TelemetryResponse,
)

router = APIRouter()


# Dependency injection helpers
def get_cache(request: Request) -> AircraftCache:
    """Retrieves the singleton AircraftCache from FastAPI app state."""
    cache = getattr(request.app.state, "cache", None)
    if cache is None:
        # Fallback singleton instantiation for testing or standalone execution
        cache = AircraftCache(max_trail_points=30)
        request.app.state.cache = cache
    return cache


def get_worker(request: Request) -> Optional[OpenSkyIngestionWorker]:
    """Retrieves the OpenSkyIngestionWorker from FastAPI app state."""
    return getattr(request.app.state, "worker", None) or getattr(request.app.state, "ingestion_worker", None)


def get_ws_manager(request: Request) -> ConnectionManager:
    """Retrieves the ConnectionManager from FastAPI app state."""
    return getattr(request.app.state, "ws_manager", None) or default_ws_manager


# ============================================================================
# 1. GET /api/telemetry
# ============================================================================

@router.get("/telemetry", response_model=TelemetryResponse, summary="Active Aircraft Telemetry")
def get_telemetry(
    anomalies_only: bool = Query(False, description="Filter for aircraft with active anomalies only"),
    limit: Optional[int] = Query(None, ge=1, description="Maximum number of aircraft to return"),
    cache: AircraftCache = Depends(get_cache),
) -> Response:
    """
    Returns active airborne vectors with full kinematic parameters,
    anomaly flags, and sliding-window trail histories.
    """
    all_flights = cache.get_all_active(airborne_only=False)
    get_dicts = getattr(cache, "get_all_active_dicts", None)
    if get_dicts is not None:
        all_dicts = get_dicts(airborne_only=False)
    else:
        all_dicts = [f.model_dump(mode="json") for f in all_flights]

    total_aircraft = len(all_flights)
    airborne_count = 0
    anomaly_count = 0
    filtered_dicts = []

    for f, d in zip(all_flights, all_dicts):
        if not f.on_ground:
            airborne_count += 1
        is_anom = f.has_anomaly or f.status != "NOMINAL"
        if is_anom:
            anomaly_count += 1
        if not anomalies_only or is_anom:
            filtered_dicts.append(d)

    if limit is not None:
        filtered_dicts = filtered_dicts[:limit]

    t_now = time.time()
    payload = {
        "timestamp": t_now,
        "total_aircraft": total_aircraft,
        "airborne_count": airborne_count,
        "anomaly_count": anomaly_count,
        "aircraft": filtered_dicts,
        "count": total_aircraft,
        "airborne": airborne_count,
        "anomalies": anomaly_count,
        "vectors": filtered_dicts,
        "flights": filtered_dicts,
    }
    return Response(content=orjson.dumps(payload), media_type="application/json")


# ============================================================================
# 2. GET /api/flight/{icao24}
# ============================================================================

@router.get("/flight/{icao24}", response_model=FlightDetailResponse, summary="Single Aircraft Kinematic Detail")
def get_flight_detail(
    icao24: str,
    cache: AircraftCache = Depends(get_cache),
) -> FlightDetailResponse:
    """
    Returns detailed kinematic trajectory history (up to 30 points)
    and operational anomaly records for a specific aircraft by ICAO24 hex address.
    Returns HTTP 404 if aircraft is not found in active tracking cache.
    """
    clean_icao = icao24.strip().lower()
    detail = cache.get_flight(clean_icao)

    if detail is None:
        return Response(
            content=orjson.dumps({"detail": f"Aircraft with ICAO24 '{clean_icao}' not found in active tracking cache"}),
            status_code=404,
            media_type="application/json",
        )

    # Access internal cache record for first_seen/last_seen timestamps if available
    rec = cache._flights.get(clean_icao) if hasattr(cache, "_flights") else None
    first_seen = getattr(rec, "first_seen", detail.last_contact)
    last_seen = getattr(rec, "last_seen", detail.last_contact)
    samples_count = len(detail.trail)

    curr_state = getattr(rec, "detail_dict", None) or detail.model_dump(mode="json")
    trail_list = [pt.model_dump(mode="json") if hasattr(pt, "model_dump") else pt for pt in detail.trail]
    anom_list = [a.model_dump(mode="json") if hasattr(a, "model_dump") else a for a in detail.anomalies]

    payload = {
        "icao24": detail.icao24,
        "callsign": detail.callsign,
        "origin_country": detail.origin_country,
        "longitude": detail.longitude,
        "latitude": detail.latitude,
        "baro_altitude": detail.baro_altitude,
        "velocity": detail.velocity,
        "vertical_rate": detail.vertical_rate,
        "squawk": detail.squawk,
        "true_track": detail.true_track,
        "on_ground": detail.on_ground,
        "last_contact": detail.last_contact,
        "geo_altitude": detail.geo_altitude,
        "status": detail.status,
        "has_anomaly": detail.has_anomaly,
        "anomalies": anom_list,
        "trail": trail_list,
        "trail_history": trail_list,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "samples_count": samples_count,
        "speed_kts": detail.speed_kts,
        "alt_ft": detail.alt_ft,
        "climb_fpm": detail.climb_fpm,
        "current_state": curr_state,
    }
    return Response(content=orjson.dumps(payload), media_type="application/json")


# ============================================================================
# 3. GET /api/anomalies
# ============================================================================

@router.get("/anomalies", response_model=AnomaliesResponse, summary="Recent Anomaly Events Feed")
def get_anomalies(
    severity: Optional[str] = Query(None, description="Optional filter by severity: CRITICAL, SEVERE, WARNING"),
    limit: Optional[int] = Query(50, ge=1, description="Maximum number of anomaly records to return"),
    cache: AircraftCache = Depends(get_cache),
) -> Response:
    """
    Returns a reverse-chronological audit log of recently detected anomaly events
    with timestamps, severity tiers, and deterministic physical rationales.
    """
    events = cache.get_recent_anomalies()

    if severity:
        target_sev = severity.strip().upper()
        events = [
            ev for ev in events
            if getattr(ev.severity, "value", str(ev.severity)).upper() == target_sev
            or str(ev.severity).upper() == target_sev
        ]

    if limit is not None:
        events = events[:limit]

    ev_dicts = [e.model_dump(mode="json") if hasattr(e, "model_dump") else e for e in events]
    payload = {
        "timestamp": time.time(),
        "total_anomalies": len(events),
        "events": ev_dicts,
        "count": len(events),
        "anomalies": ev_dicts,
    }
    return Response(content=orjson.dumps(payload), media_type="application/json")


# ============================================================================
# 4. GET /api/stats
# ============================================================================

@router.get("/stats", response_model=SystemStatsResponse, summary="Operational System Statistics")
def get_stats(
    cache: AircraftCache = Depends(get_cache),
    worker: Optional[OpenSkyIngestionWorker] = Depends(get_worker),
) -> Response:
    """
    Returns real-time aggregate statistics: active airborne counts,
    anomalies broken down by category and severity, backend uptime, and cache health.
    """
    stats = cache.get_stats()
    diagnostics = worker.get_diagnostics() if worker is not None else {}
    anomalies_by_category = stats.get("anomalies_by_category", {
        "SQUAWK_EMERGENCY": 0,
        "SEVERE_DESCENT": 0,
        "OVERSPEED_OUTLIER": 0,
    })

    cache_size = stats.get("cache_size", 0)
    payload = {
        "uptime_seconds": stats.get("uptime_seconds", 0.0),
        "total_tracked_lifetime": stats.get("total_updates", 0),
        "total_tracked": stats.get("total_tracked", 0),
        "active_airborne": stats.get("active_airborne", 0),
        "active_count": stats.get("active_airborne", 0),
        "active_on_ground": stats.get("active_on_ground", 0),
        "anomalies_total": stats.get("anomalous_count", 0),
        "anomalies_by_category": anomalies_by_category,
        "anomalies_by_severity": stats.get("anomalies_by_severity", {}),
        "anomaly_counts": stats.get("anomalies_by_severity", {}),
        "cache_size": cache_size,
        "cache_health": {
            "total_entries": cache_size,
            "memory_usage_estimate_kb": round(cache_size * 1.5, 2),
            "stale_pruned_total": stats.get("stale_pruned_total", 0),
            "last_ingestion_epoch": diagnostics.get("last_poll_timestamp"),
            "last_ingestion_status": "nominal" if diagnostics.get("consecutive_errors", 0) == 0 else "degraded",
            "ingestion_latency_ms": diagnostics.get("last_poll_duration_ms") or 0.0,
        },
    }
    return Response(content=orjson.dumps(payload), media_type="application/json")


# ============================================================================
# 5. GET /api/health
# ============================================================================

@router.get("/health", response_model=HealthResponse, summary="System Health & Ingestion Diagnostics")
def get_health(
    cache: AircraftCache = Depends(get_cache),
    worker: Optional[OpenSkyIngestionWorker] = Depends(get_worker),
    ws_mgr: ConnectionManager = Depends(get_ws_manager),
) -> Response:
    """
    Returns system liveness, active ingestion mode (LIVE_OPENSKY vs SYNTHETIC_FALLBACK),
    consecutive upstream failure counters, and connected client diagnostics.
    """
    diagnostics = worker.get_diagnostics() if worker is not None else {}
    consecutive_errors = diagnostics.get("consecutive_errors", 0)
    raw_mode = diagnostics.get("mode", "LIVE_OPENSKY")
    mode_str = getattr(raw_mode, "value", str(raw_mode))

    if mode_str == "STOPPED":
        mode_str = "LIVE_OPENSKY"

    # Status classification: healthy, degraded, or unhealthy
    if consecutive_errors == 0:
        status = "healthy"
    elif mode_str in ("SYNTHETIC_FALLBACK", "MOCK_REPLAY") or consecutive_errors > 0:
        status = "degraded"
    else:
        status = "healthy"

    opensky_connected = (consecutive_errors == 0 and mode_str == "LIVE_OPENSKY")
    cached_count = len(cache.get_all_active(airborne_only=False))

    payload = {
        "status": status,
        "mode": mode_str,
        "opensky_connected": opensky_connected,
        "consecutive_api_failures": consecutive_errors,
        "last_successful_poll": diagnostics.get("last_poll_timestamp"),
        "active_websocket_clients": ws_mgr.active_count,
        "cached_flights": cached_count,
        "version": "1.0.0",
    }
    return Response(content=orjson.dumps(payload), media_type="application/json")
