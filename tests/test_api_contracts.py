"""
tests/test_api_contracts.py - Comprehensive API Contract & Integration Tests.
Validates all 6 REST and WebSocket endpoints:
1. GET /api/telemetry (schemas, filters, limits)
2. GET /api/flight/{icao24} (existing detail, trail history, 404 handling)
3. GET /api/anomalies (events audit log, severity filter, limit)
4. GET /api/stats (system counters, anomalies breakdown, cache health)
5. GET /api/health (service status, ingestion mode, connection state)
6. GET / (static single-page HTML hosting)
7. WebSocket /ws/telemetry (initial snapshot push, text/json ping-pong, graceful disconnect)
8. Application lifespan startup and shutdown lifecycle
"""

from __future__ import annotations

import time
from typing import Any, Dict, List
import pytest
from fastapi.testclient import TestClient

from main import app
from models.schemas import (
    AnomaliesResponse,
    FlightDetailResponse,
    HealthResponse,
    SystemStatsResponse,
    TelemetryResponse,
)


@pytest.fixture
def client() -> TestClient:
    """Provides a fresh TestClient for the AeroPulse FastAPI application."""
    return TestClient(app, raise_server_exceptions=False)


# ============================================================================
# 1. GET /api/telemetry Tests
# ============================================================================

class TestGetTelemetry:
    """Validates GET /api/telemetry contract, schema conformance, and filtering."""

    def test_get_telemetry_schema(self, client: TestClient):
        """Verifies GET /api/telemetry returns HTTP 200 and matches TelemetryResponse schema."""
        response = client.get("/api/telemetry")
        assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}"

        data = response.json()
        # Validate Pydantic schema
        parsed = TelemetryResponse.model_validate(data)
        assert parsed.total_aircraft >= 0
        assert parsed.airborne_count >= 0
        assert parsed.anomaly_count >= 0
        assert len(parsed.aircraft) == parsed.total_aircraft

        # Verify wire compatibility keys
        assert "flights" in data
        assert "count" in data
        assert "airborne" in data
        assert "anomalies" in data

    def test_get_telemetry_anomalies_only_filter(self, client: TestClient):
        """Verifies anomalies_only=true returns only aircraft with active anomalies."""
        response = client.get("/api/telemetry?anomalies_only=true")
        assert response.status_code == 200

        data = response.json()
        parsed = TelemetryResponse.model_validate(data)
        for flight in parsed.aircraft:
            assert flight.has_anomaly is True or flight.status != "NOMINAL"

    def test_get_telemetry_limit_parameter(self, client: TestClient):
        """Verifies limit parameter restricts the number of returned flights."""
        response = client.get("/api/telemetry?limit=5")
        assert response.status_code == 200

        data = response.json()
        parsed = TelemetryResponse.model_validate(data)
        assert len(parsed.aircraft) <= 5


# ============================================================================
# 2. GET /api/flight/{icao24} Tests
# ============================================================================

class TestGetFlightDetail:
    """Validates GET /api/flight/{icao24} contract, trail history, and 404 handling."""

    def test_get_flight_detail_existing_aircraft(self, client: TestClient):
        """Verifies querying an active aircraft returns full FlightDetailResponse."""
        # 1. Discover an existing ICAO from telemetry
        telemetry_resp = client.get("/api/telemetry")
        assert telemetry_resp.status_code == 200
        aircraft_list = telemetry_resp.json().get("aircraft", [])
        assert len(aircraft_list) > 0, "Expected at least 1 aircraft in cache"

        target_icao = aircraft_list[0]["icao24"]

        # 2. Query flight detail
        response = client.get(f"/api/flight/{target_icao}")
        assert response.status_code == 200

        data = response.json()
        parsed = FlightDetailResponse.model_validate(data)
        assert parsed.icao24 == target_icao.lower()
        assert isinstance(parsed.trail, list)
        assert isinstance(parsed.trail_history, list)
        assert parsed.samples_count >= 0
        assert "current_state" in data

    def test_get_flight_detail_case_insensitivity(self, client: TestClient):
        """Verifies uppercase ICAO input is normalized to lowercase."""
        telemetry_resp = client.get("/api/telemetry")
        aircraft_list = telemetry_resp.json().get("aircraft", [])
        target_icao = aircraft_list[0]["icao24"]

        response = client.get(f"/api/flight/{target_icao.upper()}")
        assert response.status_code == 200
        data = response.json()
        assert data["icao24"] == target_icao.lower()

    def test_get_flight_detail_not_found(self, client: TestClient):
        """Verifies non-existent aircraft returns HTTP 404 with descriptive detail."""
        response = client.get("/api/flight/ffffff_missing")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()


# ============================================================================
# 3. GET /api/anomalies Tests
# ============================================================================

class TestGetAnomalies:
    """Validates GET /api/anomalies audit log, schema, and filtering."""

    def test_get_anomalies_schema(self, client: TestClient):
        """Verifies GET /api/anomalies returns HTTP 200 and matches AnomaliesResponse."""
        response = client.get("/api/anomalies")
        assert response.status_code == 200

        data = response.json()
        parsed = AnomaliesResponse.model_validate(data)
        assert parsed.total_anomalies >= 0
        assert isinstance(parsed.events, list)

        for event in parsed.events:
            assert event.icao24
            assert event.category
            assert event.severity
            assert event.rationale
            assert event.timestamp > 0

    def test_get_anomalies_severity_filter(self, client: TestClient):
        """Verifies severity query parameter filters anomaly events correctly."""
        response = client.get("/api/anomalies?severity=CRITICAL")
        assert response.status_code == 200

        data = response.json()
        parsed = AnomaliesResponse.model_validate(data)
        for event in parsed.events:
            assert str(event.severity).upper() in ("CRITICAL", "ANOMALYSEVERITY.CRITICAL")

    def test_get_anomalies_limit(self, client: TestClient):
        """Verifies limit parameter restricts the count of returned anomaly events."""
        response = client.get("/api/anomalies?limit=2")
        assert response.status_code == 200

        data = response.json()
        parsed = AnomaliesResponse.model_validate(data)
        assert len(parsed.events) <= 2


# ============================================================================
# 4. GET /api/stats Tests
# ============================================================================

class TestGetStats:
    """Validates GET /api/stats counters, uptime, and cache health diagnostics."""

    def test_get_stats_schema(self, client: TestClient):
        """Verifies GET /api/stats returns HTTP 200 and matches SystemStatsResponse."""
        response = client.get("/api/stats")
        assert response.status_code == 200

        data = response.json()
        parsed = SystemStatsResponse.model_validate(data)
        assert parsed.uptime_seconds >= 0.0
        assert parsed.total_tracked >= 0
        assert parsed.active_airborne >= 0
        assert parsed.active_count == parsed.active_airborne
        assert isinstance(parsed.anomalies_by_category, dict)
        assert isinstance(parsed.anomalies_by_severity, dict)

        # Cache health checks
        assert parsed.cache_health.total_entries >= 0
        assert parsed.cache_health.memory_usage_estimate_kb >= 0.0


# ============================================================================
# 5. GET /api/health Tests
# ============================================================================

class TestGetHealth:
    """Validates GET /api/health service status and ingestion diagnostics."""

    def test_get_health_schema(self, client: TestClient):
        """Verifies GET /api/health returns HTTP 200 and matches HealthResponse."""
        response = client.get("/api/health")
        assert response.status_code == 200

        data = response.json()
        parsed = HealthResponse.model_validate(data)
        assert parsed.status in ("healthy", "degraded", "unhealthy", "ok", "UP")
        assert parsed.mode in ("LIVE_OPENSKY", "SYNTHETIC_FALLBACK", "MOCK_REPLAY")
        assert isinstance(parsed.opensky_connected, bool)
        assert parsed.consecutive_api_failures >= 0
        assert parsed.version == "1.0.0"


# ============================================================================
# 6. GET / Static File Serving Tests
# ============================================================================

class TestStaticFileServing:
    """Validates static assets mount and root index.html serving."""

    def test_root_serves_html(self, client: TestClient):
        """Verifies GET / returns HTTP 200 with text/html content type."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert "AeroPulse" in response.text


# ============================================================================
# 7. WebSocket /ws/telemetry Tests
# ============================================================================

class TestWebSocketTelemetry:
    """Validates WebSocket streaming, snapshot push, ping-pong, and disconnection."""

    def test_websocket_snapshot_and_ping_pong(self, client: TestClient):
        """
        Tests WebSocket lifecycle:
        1. Connects to /ws/telemetry.
        2. Receives immediate 'SNAPSHOT' payload.
        3. Sends string 'PING' -> receives 'PONG'.
        4. Sends JSON 'PING' -> receives 'PONG'.
        5. Gracefully disconnects.
        """
        with client.websocket_connect("/ws/telemetry") as ws:
            # 1. Initial SNAPSHOT payload verification
            snapshot_msg = ws.receive_json()
            assert snapshot_msg.get("event") == "SNAPSHOT" or snapshot_msg.get("type") == "SNAPSHOT"
            assert "data" in snapshot_msg

            data = snapshot_msg["data"]
            # Verify data can be validated as TelemetryResponse
            parsed_telemetry = TelemetryResponse.model_validate(data)
            assert parsed_telemetry.total_aircraft >= 0

            # 2. String PING verification
            ws.send_text("PING")
            pong_msg = ws.receive_json()
            assert pong_msg.get("event") == "PONG" or pong_msg.get("type") == "PONG"

            # 3. JSON PING verification
            ws.send_json({"type": "PING"})
            pong_json = ws.receive_json()
            assert pong_json.get("event") == "PONG" or pong_json.get("type") == "PONG"

    def test_websocket_graceful_disconnect(self, client: TestClient):
        """Verifies client disconnection is handled safely without unhandled server exceptions."""
        with client.websocket_connect("/ws/telemetry") as ws:
            msg = ws.receive_json()
            assert "data" in msg
        # Leaving context triggers WebSocket close


# ============================================================================
# 8. Lifespan Integration Test
# ============================================================================

class TestApplicationLifespan:
    """Verifies FastAPI lifespan startup and shutdown context manager execution."""

    def test_lifespan_starts_and_stops_cleanly(self):
        """Verifies entering TestClient context triggers lifespan startup and cleanly terminates."""
        with TestClient(app) as test_client:
            # Verify server is healthy within lifespan
            health = test_client.get("/api/health")
            assert health.status_code == 200
            assert health.json()["status"] in ("healthy", "degraded", "ok")

            # Verify telemetry is populated
            telemetry = test_client.get("/api/telemetry")
            assert telemetry.status_code == 200
            assert telemetry.json()["total_aircraft"] > 0
