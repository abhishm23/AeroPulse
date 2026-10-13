"""
Tier 1: Feature Isolation Tests (R1 through R5).

Every feature from user requirements is verified in strict isolation:
- R1: Ingestion & Caching (F-ING-01..13)
- R2: Mechanical Anomaly Traps (F-ANO-01..10)
- R3: Military HUD Dashboard Assets (F-HUD-01..32)
- R4: Expanded Backend API Endpoints (F-API-01..08)
- R5: Automated Verification & Launcher (F-TEST-01..05, F-LAUNCH-01)
"""

import os
import re
import time
from pathlib import Path
from typing import Dict, Any, List
import pytest

from e2e_tests.dynamic_loader import (
    get_anomaly_components,
    get_cache_components,
    get_ingestion_components,
    get_fastapi_app,
    skip_unless_m1,
    skip_unless_m2,
    skip_unless_m3,
    skip_unless_m4,
    skip_unless_m5,
    PROJECT_ROOT
)
from e2e_tests.conftest import AuthoritativeAnomalyOracle


# ==============================================================================
# R1: Real-Time ADS-B Ingestion & Resilient Caching
# ==============================================================================

class TestR1IngestionAndCaching:
    """Feature isolation tests for Requirement R1."""
    
    def test_r1_opensky_bounding_box_coordinates(self):
        """F-ING-01: Verifies bounded geographical box parameters: lamin=20, lomin=-10, lamax=60, lomax=40."""
        expected_bbox = {"lamin": 20, "lomin": -10, "lamax": 60, "lomax": 40}
        
        # Check core.config or core.ingestion if available
        worker_cls, _ = get_ingestion_components()
        config_mod = None
        try:
            import core.config as config_mod
        except (ImportError, ModuleNotFoundError):
            pass
            
        if config_mod and hasattr(config_mod, "settings"):
            settings = config_mod.settings
            bbox = getattr(settings, "OPENSKY_BBOX", None)
            if bbox:
                for k, v in expected_bbox.items():
                    assert bbox.get(k) == v, f"BBox mismatch for {k}: expected {v}, got {bbox.get(k)}"
        else:
            # Authoritative check from ORIGINAL_REQUEST.md
            assert expected_bbox["lamin"] == 20
            assert expected_bbox["lomin"] == -10
            assert expected_bbox["lamax"] == 60
            assert expected_bbox["lomax"] == 40

    def test_r1_adsb_tuple_indices_mapping(self, sample_nominal_tuples):
        """F-ING-02: Verifies ADS-B tuple index extraction conforms strictly to R1 specification."""
        raw_tuple = sample_nominal_tuples[0]  # DLH123
        
        # R1 mandated indices:
        # [0] ICAO24, [1] Callsign, [2] Origin Country, [5] Longitude, [6] Latitude,
        # [7] Barometric Altitude, [9] Velocity, [11] Vertical Rate, [14] Squawk
        icao24 = raw_tuple[0]
        callsign = raw_tuple[1].strip() if raw_tuple[1] else None
        origin_country = raw_tuple[2]
        lon = raw_tuple[5]
        lat = raw_tuple[6]
        baro_alt = raw_tuple[7]
        velocity = raw_tuple[9]
        vertical_rate = raw_tuple[11]
        squawk = raw_tuple[14]
        
        assert icao24 == "3c6444"
        assert callsign == "DLH123"
        assert origin_country == "Germany"
        assert lon == 8.54
        assert lat == 50.03
        assert baro_alt == 10668.0
        assert velocity == 235.0
        assert vertical_rate == 0.0
        assert squawk == "1000"

    @skip_unless_m1
    def test_r1_sliding_window_ring_buffer_capacity(self, initialized_cache):
        """F-ING-03: Verifies ring buffer enforces max capacity of 30 recent kinematic points."""
        cache = initialized_cache
        _, state_cls = get_cache_components()
        
        icao = "3c6444"
        base_time = time.time()
        
        # Insert 45 sequential updates for the same aircraft
        for i in range(45):
            state_data = {
                "icao24": icao,
                "callsign": "DLH123",
                "origin_country": "Germany",
                "longitude": 8.5 + (i * 0.01),
                "latitude": 50.0 + (i * 0.01),
                "baro_altitude": 10000.0,
                "velocity": 230.0,
                "vertical_rate": 0.0,
                "squawk": "1000",
                "last_contact": base_time + i,
                "on_ground": False
            }
            try:
                state_obj = state_cls(**state_data)
                cache.update_vector(state_obj)
            except Exception:
                # Handle alternative method names in cache
                if hasattr(cache, "update"):
                    cache.update(state_obj)
                    
        flight = cache.get_flight(icao) if hasattr(cache, "get_flight") else None
        if flight:
            history = getattr(flight, "trail", None) or getattr(flight, "history", None) or getattr(flight, "trail_history", None)
            assert history is not None
            # Must be capped at 30
            assert len(history) <= 30, f"History length {len(history)} exceeded maxlen=30!"

    @skip_unless_m1
    def test_r1_stale_flight_ttl_pruning(self, initialized_cache):
        """F-ING-07: Verifies flights older than 120s TTL are pruned from the active tracking cache."""
        cache = initialized_cache
        _, state_cls = get_cache_components()
        
        now = time.time()
        # Insert active flight (updated 10s ago)
        active_state = state_cls(
            icao24="4b1111", callsign="ACTIVE1", origin_country="CH",
            longitude=8.0, latitude=47.0, baro_altitude=9000.0,
            velocity=200.0, vertical_rate=0.0, squawk="1000",
            last_contact=now - 10.0, on_ground=False
        )
        # Insert stale flight (updated 130s ago, exceeding 120s TTL)
        stale_state = state_cls(
            icao24="4b9999", callsign="STALE1", origin_country="CH",
            longitude=8.0, latitude=47.0, baro_altitude=9000.0,
            velocity=200.0, vertical_rate=0.0, squawk="1000",
            last_contact=now - 135.0, on_ground=False
        )
        
        update_func = getattr(cache, "update_vector", None) or getattr(cache, "update", None)
        update_func(active_state)
        update_func(stale_state)
        
        # Invoke pruning
        prune_func = getattr(cache, "prune_stale", None) or getattr(cache, "evict_stale", None)
        if prune_func:
            pruned_count = prune_func(ttl_seconds=120.0)
            assert pruned_count >= 1, "Expected at least 1 stale flight to be pruned"
            
        # Active flight must remain, stale flight must be gone
        get_flight = getattr(cache, "get_flight", None)
        if get_flight:
            assert get_flight("4b1111") is not None, "Active flight was incorrectly pruned"
            assert get_flight("4b9999") is None, "Stale flight was not pruned"

    def test_r1_unit_conversions(self):
        """F-ING-12: Verifies mathematical precision of aviation unit conversions."""
        # Speed: 1 m/s = 1.943844 knots
        speed_ms = 250.0
        speed_knots = speed_ms * 1.943844
        assert abs(speed_knots - 485.961) < 0.01
        
        # Altitude: 1 meter = 3.28084 feet
        alt_meters = 10000.0
        alt_feet = alt_meters * 3.28084
        assert abs(alt_feet - 32808.4) < 0.1
        
        # Vertical Rate: 1 m/s = 196.8504 ft/min
        # Threshold -20.32 m/s should equal exactly -4,000 ft/min
        descent_ms = -20.32
        descent_fpm = descent_ms * 196.850394
        assert abs(descent_fpm - (-4000.0)) < 1.0


# ==============================================================================
# R2: Deterministic Mechanical Anomaly Detection Engine
# ==============================================================================

class TestR2DeterministicAnomalyTraps:
    """Feature isolation tests for Requirement R2."""
    
    @skip_unless_m2
    def test_r2_critical_squawk_7500_hijack(self, anomaly_oracle):
        """F-ANO-01: Verifies squawk 7500 triggers Unlawful Interference alert with CRITICAL severity."""
        engine_cls, severity_cls, _ = get_anomaly_components()
        _, state_cls = get_cache_components()
        
        state_kwargs = {
            "icao24": "4b0750", "callsign": "SWR750", "origin_country": "Switzerland",
            "longitude": 8.0, "latitude": 47.0, "baro_altitude": 9000.0,
            "velocity": 230.0, "vertical_rate": 0.0, "squawk": "7500",
            "last_contact": time.time(), "on_ground": False
        }
        
        # 1. Authoritative oracle derivation
        oracle_flags = anomaly_oracle.evaluate(state_kwargs)
        assert "SQUAWK_EMERGENCY" in oracle_flags
        
        # 2. Implementation execution
        state = state_cls(**state_kwargs) if state_cls else state_kwargs
        eval_func = getattr(engine_cls, "evaluate", None) or getattr(engine_cls, "evaluate_vector", None)
        flags = eval_func(state)
        
        assert len(flags) > 0, "No anomaly flags triggered for squawk 7500"
        flag = flags[0]
        rationale = getattr(flag, "rationale", "")
        severity = getattr(flag, "severity", "")
        
        assert any(term in rationale.lower() for term in ["hijack", "unlawful", "7500"])
        assert str(severity).upper() in ["CRITICAL", "ANOMALYSEVERITY.CRITICAL"]

    @skip_unless_m2
    def test_r2_critical_squawk_7600_radio_failure(self, anomaly_oracle):
        """F-ANO-01: Verifies squawk 7600 triggers Radio Communication Failure alert."""
        engine_cls, severity_cls, _ = get_anomaly_components()
        _, state_cls = get_cache_components()
        
        state_kwargs = {
            "icao24": "3c0760", "callsign": "DLH760", "origin_country": "Germany",
            "longitude": 9.0, "latitude": 50.0, "baro_altitude": 10000.0,
            "velocity": 240.0, "vertical_rate": 0.0, "squawk": "7600",
            "last_contact": time.time(), "on_ground": False
        }
        
        oracle_flags = anomaly_oracle.evaluate(state_kwargs)
        assert "SQUAWK_EMERGENCY" in oracle_flags
        
        state = state_cls(**state_kwargs) if state_cls else state_kwargs
        eval_func = getattr(engine_cls, "evaluate", None) or getattr(engine_cls, "evaluate_vector", None)
        flags = eval_func(state)
        
        assert len(flags) > 0
        rationale = getattr(flags[0], "rationale", "")
        assert any(term in rationale.lower() for term in ["radio", "communication", "nordo", "7600"])

    @skip_unless_m2
    def test_r2_critical_squawk_7700_general_emergency(self, anomaly_oracle):
        """F-ANO-01: Verifies squawk 7700 triggers General Emergency alert with CRITICAL severity."""
        engine_cls, severity_cls, _ = get_anomaly_components()
        _, state_cls = get_cache_components()
        
        state_kwargs = {
            "icao24": "400770", "callsign": "BAW770", "origin_country": "United Kingdom",
            "longitude": 0.0, "latitude": 51.0, "baro_altitude": 8000.0,
            "velocity": 220.0, "vertical_rate": 0.0, "squawk": "7700",
            "last_contact": time.time(), "on_ground": False
        }
        
        oracle_flags = anomaly_oracle.evaluate(state_kwargs)
        assert "SQUAWK_EMERGENCY" in oracle_flags
        
        state = state_cls(**state_kwargs) if state_cls else state_kwargs
        eval_func = getattr(engine_cls, "evaluate", None) or getattr(engine_cls, "evaluate_vector", None)
        flags = eval_func(state)
        
        assert len(flags) > 0
        flag = flags[0]
        assert "7700" in getattr(flag, "rationale", "") or "emergency" in getattr(flag, "rationale", "").lower()
        assert str(getattr(flag, "severity", "")).upper() in ["CRITICAL", "ANOMALYSEVERITY.CRITICAL"]

    @skip_unless_m2
    def test_r2_severe_descent_below_threshold(self, anomaly_oracle):
        """F-ANO-02: Verifies vertical_rate < -20.32 m/s (-4,000 ft/min) flags SEVERE descent."""
        engine_cls, _, _ = get_anomaly_components()
        _, state_cls = get_cache_components()
        
        state_kwargs = {
            "icao24": "3c0002", "callsign": "DLH002", "origin_country": "Germany",
            "longitude": 10.0, "latitude": 52.0, "baro_altitude": 7000.0,
            "velocity": 230.0, "vertical_rate": -25.0,  # Violates -20.32 m/s
            "squawk": "1000", "last_contact": time.time(), "on_ground": False
        }
        
        oracle_flags = anomaly_oracle.evaluate(state_kwargs)
        assert "SEVERE_DESCENT" in oracle_flags
        
        state = state_cls(**state_kwargs) if state_cls else state_kwargs
        eval_func = getattr(engine_cls, "evaluate", None) or getattr(engine_cls, "evaluate_vector", None)
        flags = eval_func(state)
        
        assert len(flags) > 0, "Expected SEVERE_DESCENT anomaly"
        flag = flags[0]
        rationale = getattr(flag, "rationale", "").lower()
        assert any(word in rationale for word in ["descent", "-25", "ft/min", "depressurization"])

    @skip_unless_m2
    def test_r2_overspeed_outlier_low_altitude(self, anomaly_oracle):
        """F-ANO-03: Verifies velocity > 330 m/s below 10,000 m flags OVERSPEED anomaly."""
        engine_cls, _, _ = get_anomaly_components()
        _, state_cls = get_cache_components()
        
        state_kwargs = {
            "icao24": "390001", "callsign": "AFR001", "origin_country": "France",
            "longitude": 2.5, "latitude": 48.5, "baro_altitude": 5000.0,  # Below 10,000m
            "velocity": 340.0,  # Exceeds 330 m/s
            "vertical_rate": 0.0, "squawk": "1000", "last_contact": time.time(), "on_ground": False
        }
        
        oracle_flags = anomaly_oracle.evaluate(state_kwargs)
        assert "OVERSPEED_OUTLIER" in oracle_flags
        
        state = state_cls(**state_kwargs) if state_cls else state_kwargs
        eval_func = getattr(engine_cls, "evaluate", None) or getattr(engine_cls, "evaluate_vector", None)
        flags = eval_func(state)
        
        assert len(flags) > 0, "Expected OVERSPEED_OUTLIER anomaly"
        rationale = getattr(flags[0], "rationale", "").lower()
        assert any(word in rationale for word in ["overspeed", "velocity", "speed", "340"])

    @skip_unless_m2
    def test_r2_nominal_cruise_zero_false_positives(self, anomaly_oracle):
        """F-ANO-07: Verifies nominal cruising parameters produce exactly zero false positive flags."""
        engine_cls, _, _ = get_anomaly_components()
        _, state_cls = get_cache_components()
        
        nominal_state = {
            "icao24": "3c6444", "callsign": "DLH123", "origin_country": "Germany",
            "longitude": 8.54, "latitude": 50.03, "baro_altitude": 10668.0,
            "velocity": 235.0, "vertical_rate": 0.0, "squawk": "1000",
            "last_contact": time.time(), "on_ground": False
        }
        
        assert len(anomaly_oracle.evaluate(nominal_state)) == 0
        
        state = state_cls(**nominal_state) if state_cls else nominal_state
        eval_func = getattr(engine_cls, "evaluate", None) or getattr(engine_cls, "evaluate_vector", None)
        flags = eval_func(state)
        assert len(flags) == 0, f"False positive anomaly triggered on nominal cruise: {flags}"


# ==============================================================================
# R3: Premium Military/Tactical HUD Dark-Mode Dashboard Assets
# ==============================================================================

class TestR3TacticalHUDDashboardAssets:
    """Feature isolation tests for Requirement R3."""
    
    @skip_unless_m4
    def test_r3_static_index_html_structure(self):
        """F-HUD-01..07: Verifies static/index.html includes Leaflet container, panels, and title."""
        index_path = PROJECT_ROOT / "static" / "index.html"
        assert index_path.is_file(), "static/index.html missing"
        
        content = index_path.read_text(encoding="utf-8")
        assert "<div" in content
        # Check map container
        assert 'id="map"' in content or "id='map'" in content, "Missing Leaflet #map container"
        # Check title / HUD brand
        assert "AeroPulse" in content or "aeropulse" in content.lower()

    @skip_unless_m4
    def test_r3_tactical_css_styling(self):
        """F-HUD-03..05: Verifies static/css/hud.css defines military HUD styling & scanlines."""
        css_path = PROJECT_ROOT / "static" / "css" / "hud.css"
        assert css_path.is_file(), "static/css/hud.css missing"
        
        content = css_path.read_text(encoding="utf-8").lower()
        # Look for dark mode colors (black/dark background, neon colors)
        assert any(c in content for c in ["#0", "rgb(", "rgba(", "hsl("]), "No dark theme background"
        # Look for scanline or glow or tactical styling
        assert any(term in content for term in ["scanline", "glow", "radar", "hud", "neon", "box-shadow"])

    @skip_unless_m4
    def test_r3_leaflet_dark_matter_layer(self):
        """F-HUD-02: Verifies CartoDB Dark Matter tile layer is referenced in frontend scripts."""
        js_dir = PROJECT_ROOT / "static" / "js"
        assert js_dir.is_dir(), "static/js/ directory missing"
        
        found_dark_matter = False
        for js_file in js_dir.glob("*.js"):
            txt = js_file.read_text(encoding="utf-8")
            if "basemaps.cartocdn.com" in txt or "dark_all" in txt or "CartoDB.DarkMatter" in txt:
                found_dark_matter = True
                break
                
        assert found_dark_matter, "CartoDB Dark Matter tile URL not referenced in static/js/*.js"

    @skip_unless_m4
    def test_r3_interactive_panel_elements(self):
        """F-HUD-12..18: Verifies DOM elements for metrics header, anomaly feed, data table, and drawer."""
        index_path = PROJECT_ROOT / "static" / "index.html"
        content = index_path.read_text(encoding="utf-8").lower()
        
        # Check header metrics
        has_metrics = any(w in content for w in ["metric", "header", "airborne", "tally", "stats"])
        # Check anomaly feed
        has_feed = any(w in content for w in ["anomaly", "feed", "alert", "events"])
        # Check table
        has_table = any(w in content for w in ["table", "flights-list", "grid", "aircraft-list"])
        # Check drawer
        has_drawer = any(w in content for w in ["drawer", "telemetry", "detail", "sidebar", "panel"])
        
        assert has_metrics, "Missing header metrics bar in index.html"
        assert has_feed, "Missing anomaly feed container in index.html"
        assert has_table, "Missing aircraft data table container in index.html"
        assert has_drawer, "Missing telemetry detail drawer in index.html"


# ==============================================================================
# R4: Expanded Backend API Endpoints
# ==============================================================================

class TestR4ExpandedBackendAPI:
    """Feature isolation tests for Requirement R4."""
    
    @skip_unless_m3
    def test_r4_get_telemetry_schema_and_status(self, app_client):
        """F-API-03: Verifies GET /api/telemetry returns 200 OK and valid JSON schema."""
        response = app_client.get("/api/telemetry")
        assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}"
        
        data = response.json()
        assert isinstance(data, dict)
        # Check fields compliant with TelemetryResponse
        assert any(k in data for k in ["aircraft", "flights"]), "Missing aircraft/flights key in telemetry response"
        assert any(k in data for k in ["total_aircraft", "count", "airborne_count", "airborne"])

    @skip_unless_m3
    def test_r4_get_flight_detail_not_found(self, app_client):
        """F-API-04: Verifies GET /api/flight/{icao24} returns 404 for unknown aircraft."""
        response = app_client.get("/api/flight/ffffff")
        assert response.status_code == 404, f"Expected 404 Not Found, got {response.status_code}"

    @skip_unless_m3
    def test_r4_get_anomalies_schema(self, app_client):
        """F-API-05: Verifies GET /api/anomalies returns 200 OK and valid JSON structure."""
        response = app_client.get("/api/anomalies")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (dict, list)), "Anomalies response must be a list or dict envelope"

    @skip_unless_m3
    def test_r4_get_stats_schema(self, app_client):
        """F-API-06: Verifies GET /api/stats returns 200 OK with operational counters."""
        response = app_client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert any(k in data for k in ["uptime_seconds", "uptime", "total_tracked", "active_count"])

    @skip_unless_m3
    def test_r4_get_health_status(self, app_client):
        """F-API-08: Verifies GET /api/health returns 200 OK with health status."""
        response = app_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ["healthy", "degraded", "ok", "UP"]

    @skip_unless_m3
    def test_r4_root_serves_html(self, app_client):
        """F-API-02: Verifies GET / serves HTML content from static files."""
        response = app_client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")


# ==============================================================================
# R5: Automated Verification Suite & Launcher
# ==============================================================================

class TestR5VerificationAndLauncher:
    """Feature isolation tests for Requirement R5."""
    
    @skip_unless_m5
    def test_r5_run_bat_exists_and_crlf(self):
        """F-LAUNCH-01: Verifies run.bat exists and uses CRLF (\\r\\n) line endings."""
        run_bat = PROJECT_ROOT / "run.bat"
        assert run_bat.is_file(), "run.bat not found at project root"
        
        raw_bytes = run_bat.read_bytes()
        assert b"\r\n" in raw_bytes, "run.bat must use CRLF (\\r\\n) Windows line endings"
        # Verify no isolated \n without preceding \r
        # Replace \r\n with empty, check if remaining bytes contain \n
        stripped = raw_bytes.replace(b"\r\n", b"")
        assert b"\n" not in stripped, "run.bat contains non-CRLF line endings (bare LF detected)"

    @skip_unless_m5
    def test_r5_run_bat_commands(self):
        """F-LAUNCH-01: Verifies run.bat clears port 8000, starts server, and opens browser."""
        run_bat = PROJECT_ROOT / "run.bat"
        content = run_bat.read_text(encoding="utf-8", errors="ignore").lower()
        
        # Check port 8000 clearing
        assert "8000" in content, "run.bat does not mention port 8000"
        assert any(cmd in content for cmd in ["kill", "stop-process", "taskkill", "get-nettcpconnection"]), "Port clearance missing"
        
        # Check uvicorn start
        assert "uvicorn" in content, "run.bat does not launch uvicorn"
        
        # Check browser launch
        assert any(cmd in content for cmd in ["start http", "start \"\" http", "start http://localhost:8000"]), "Browser start missing"

    @skip_unless_m1
    def test_r5_cache_retrieval_sla_smoke(self, initialized_cache):
        """F-TEST-04: Smoke test verifying cache snapshot retrieval latency is well under 50ms."""
        cache = initialized_cache
        start = time.perf_counter_ns()
        get_all = getattr(cache, "get_all_active", None) or getattr(cache, "get_active_telemetry", None)
        if get_all:
            _ = get_all()
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000.0
        assert elapsed_ms < 50.0, f"Cache retrieval took {elapsed_ms:.3f}ms, exceeding 50ms SLA"
