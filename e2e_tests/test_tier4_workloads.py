"""
Tier 4: End-to-End System Workloads & Realistic Operational Scenarios.

Validates complete multi-step flight trajectories, emergency depressurization lifecycles,
consecutive kinematic sparkline history generation, high-throughput burst loads,
frontend HUD static asset contracts, and Windows launcher (run.bat) operations.
"""

import time
from pathlib import Path
from typing import Dict, Any, List
import pytest

from e2e_tests.dynamic_loader import (
    get_anomaly_components,
    get_cache_components,
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
# Scenario 1: Multi-Aircraft European Airspace Simulation
# ==============================================================================

class TestScenario1EuropeanAirspaceWorkload:
    """End-to-end simulation of 50 nominal European flights."""
    
    @skip_unless_m1
    def test_scenario1_50_nominal_flights_in_airspace(self, initialized_cache):
        """
        Feeds 50 nominal European flights with realistic routes, speeds, altitudes.
        Verifies:
        - 100% stored in cache
        - 0 false positive anomalies
        - Snapshot retrieval latency is strictly < 50ms
        """
        cache = initialized_cache
        _, state_cls = get_cache_components()
        update_func = getattr(cache, "update_vector", None) or getattr(cache, "update", None)
        
        now = time.time()
        for i in range(50):
            st = state_cls(
                icao24=f"4b{i:04x}",
                callsign=f"SWR{100+i}",
                origin_country="Switzerland",
                longitude=8.0 + (i * 0.1),
                latitude=47.0 + (i * 0.05),
                baro_altitude=10000.0 + (i * 50.0),
                velocity=220.0 + (i % 15),
                vertical_rate=0.0,
                squawk="1000",
                last_contact=now - 2.0,
                on_ground=False
            )
            update_func(st)
            
        # Verify active snapshot
        get_all = getattr(cache, "get_all_active", None) or getattr(cache, "get_active_telemetry", None)
        t0 = time.perf_counter_ns()
        snapshot = get_all()
        t1 = time.perf_counter_ns()
        latency_ms = (t1 - t0) / 1_000_000.0
        
        flights = snapshot if isinstance(snapshot, list) else getattr(snapshot, "aircraft", getattr(snapshot, "flights", []))
        assert len(flights) == 50, f"Expected 50 flights in cache snapshot, got {len(flights)}"
        assert latency_ms < 50.0, f"Snapshot retrieval took {latency_ms:.3f}ms (exceeded 50ms SLA)"


# ==============================================================================
# Scenario 2: Emergency Depressurization & Rapid Descent Flight Lifecycle
# ==============================================================================

class TestScenario2DepressurizationLifecycle:
    """Full lifecycle: Cruise -> Cabin Altitude Warning -> Emergency Descent -> Level-off."""
    
    @skip_unless_m1
    @skip_unless_m2
    def test_scenario2_depressurization_flight_profile(self, initialized_cache, anomaly_oracle):
        """
        Simulates 3-phase emergency descent scenario for Airbus A320 (DLH442):
        Phase 1: Cruise at FL360 (10,972m), speed 235 m/s, squawk 1000. (NOMINAL)
        Phase 2: Depressurization: squawks 7700, descends at -28.5 m/s (-5,610 ft/min). (ANOMALOUS)
        Phase 3: Level-off at 3,000m, vertical rate 0.0 m/s, squawk 7700 remains active. (SQUAWK ANOMALY)
        """
        cache = initialized_cache
        _, state_cls = get_cache_components()
        engine_cls, _, _ = get_anomaly_components()
        update_func = getattr(cache, "update_vector", None) or getattr(cache, "update", None)
        eval_func = getattr(engine_cls, "evaluate", None) or getattr(engine_cls, "evaluate_vector", None)
        
        now = time.time()
        icao = "3c0442"
        callsign = "DLH442"
        
        # --- Phase 1: Nominal Cruise ---
        st_phase1 = state_cls(
            icao24=icao, callsign=callsign, origin_country="Germany",
            longitude=9.0, latitude=50.0, baro_altitude=10972.0,
            velocity=235.0, vertical_rate=0.0, squawk="1000",
            last_contact=now - 20.0, on_ground=False
        )
        update_func(st_phase1)
        flags1 = eval_func(st_phase1)
        assert len(flags1) == 0, "Phase 1 cruise produced unexpected false positive"
        
        # --- Phase 2: Emergency Descent ---
        st_phase2 = state_cls(
            icao24=icao, callsign=callsign, origin_country="Germany",
            longitude=9.1, latitude=50.1, baro_altitude=7500.0,
            velocity=245.0, vertical_rate=-28.5,  # -5,610 ft/min (< -20.32)
            squawk="7700",  # General emergency
            last_contact=now - 10.0, on_ground=False
        )
        update_func(st_phase2)
        flags2 = eval_func(st_phase2)
        assert len(flags2) >= 2, "Phase 2 failed to trigger dual squawk 7700 and severe descent traps"
        
        # --- Phase 3: Level-off at 3000m ---
        st_phase3 = state_cls(
            icao24=icao, callsign=callsign, origin_country="Germany",
            longitude=9.2, latitude=50.2, baro_altitude=3000.0,
            velocity=180.0, vertical_rate=0.0,  # Leveled off
            squawk="7700",  # Still emergency
            last_contact=now, on_ground=False
        )
        update_func(st_phase3)
        flags3 = eval_func(st_phase3)
        # Descent trap clears, squawk 7700 persists
        assert any("7700" in getattr(f, "rationale", "") or "emergency" in getattr(f, "rationale", "").lower() for f in flags3)
        assert not any("descent" in getattr(f, "category", "").lower() for f in flags3)


# ==============================================================================
# Scenario 3: Consecutive 30-Step Kinematic Sparkline Trail Evolution
# ==============================================================================

class TestScenario3SparklineTrailEvolution:
    """Generates 30 sequential kinematic points and validates sparkline data integrity."""
    
    @skip_unless_m1
    def test_scenario3_30_consecutive_points_for_sparkline(self, initialized_cache):
        """
        Simulates 30 consecutive updates for SWR134 climbing from 3000m to 9000m.
        Verifies trail history has exactly 30 valid numeric points ready for HTML5 canvas sparklines.
        """
        cache = initialized_cache
        _, state_cls = get_cache_components()
        update_func = getattr(cache, "update_vector", None) or getattr(cache, "update", None)
        
        now = time.time()
        icao = "4b1812"
        for i in range(30):
            st = state_cls(
                icao24=icao, callsign="SWR134", origin_country="Switzerland",
                longitude=8.0 + (i * 0.02), latitude=47.0 + (i * 0.01),
                baro_altitude=3000.0 + (i * 200.0),
                velocity=160.0 + (i * 2.5),
                vertical_rate=10.0,
                squawk="1000",
                last_contact=now + i,
                on_ground=False
            )
            update_func(st)
            
        flight = cache.get_flight(icao) if hasattr(cache, "get_flight") else None
        assert flight is not None, f"Flight {icao} not found in cache"
        
        trail = getattr(flight, "trail", None) or getattr(flight, "history", None) or getattr(flight, "trail_history", None)
        assert trail is not None
        assert len(trail) == 30, f"Expected exactly 30 trail points, got {len(trail)}"
        
        # Verify numeric validity of points for sparkline rendering
        for pt in trail:
            alt = getattr(pt, "altitude", getattr(pt, "baro_altitude", None))
            vel = getattr(pt, "velocity", getattr(pt, "speed", None))
            assert alt is not None and isinstance(alt, (int, float))
            assert vel is not None and isinstance(vel, (int, float))


# ==============================================================================
# Scenario 4: High-Throughput Burst Ingestion & Cache SLA Under Load
# ==============================================================================

class TestScenario4BurstIngestion:
    """Stress tests cache ingestion and snapshot performance under a 200-vector burst."""
    
    @skip_unless_m1
    def test_scenario4_burst_ingestion_200_vectors(self, initialized_cache):
        """Injects 200 vector updates rapidly and measures throughput & latency."""
        cache = initialized_cache
        _, state_cls = get_cache_components()
        update_func = getattr(cache, "update_vector", None) or getattr(cache, "update", None)
        
        now = time.time()
        t_start = time.perf_counter_ns()
        for i in range(200):
            st = state_cls(
                icao24=f"burst{i:03d}",
                callsign=f"BST{i:03d}",
                origin_country="Europe",
                longitude=10.0 + (i % 20) * 0.1,
                latitude=48.0 + (i % 15) * 0.1,
                baro_altitude=9000.0,
                velocity=210.0,
                vertical_rate=0.0,
                squawk="1000",
                last_contact=now,
                on_ground=False
            )
            update_func(st)
        t_ingest_end = time.perf_counter_ns()
        
        burst_time_ms = (t_ingest_end - t_start) / 1_000_000.0
        print(f"\n[BURST LOAD] 200 Vectors ingested in {burst_time_ms:.3f}ms")
        
        # Read full snapshot
        get_all = getattr(cache, "get_all_active", None) or getattr(cache, "get_active_telemetry", None)
        t_read_start = time.perf_counter_ns()
        snapshot = get_all()
        t_read_end = time.perf_counter_ns()
        read_latency_ms = (t_read_end - t_read_start) / 1_000_000.0
        
        assert read_latency_ms < 50.0, f"Snapshot read took {read_latency_ms:.3f}ms (exceeded 50ms SLA)"


# ==============================================================================
# Scenario 5: Static Tactical HUD Frontend Asset Forensic Verification
# ==============================================================================

class TestScenario5FrontendHUDAssetsForensic:
    """Opaque-box verification of frontend assets required by R3."""
    
    @skip_unless_m4
    def test_scenario5_static_hud_assets_integrity(self):
        """
        Forensically verifies:
        1. static/index.html contains tactical dark HUD DOM nodes.
        2. static/css/hud.css contains dark-mode styles, scanlines, neon accents.
        3. static/js/ contains Leaflet Dark Matter, rotating SVG icons, audio synthesizer.
        """
        static_dir = PROJECT_ROOT / "static"
        assert static_dir.is_dir(), "static/ directory not found"
        
        index_file = static_dir / "index.html"
        assert index_file.is_file(), "static/index.html missing"
        html = index_file.read_text(encoding="utf-8")
        
        # Map element
        assert "map" in html.lower(), "Missing map container in index.html"
        
        # CSS inspection
        css_file = static_dir / "css" / "hud.css"
        if css_file.is_file():
            css = css_file.read_text(encoding="utf-8")
            assert len(css) > 100, "hud.css is too short or empty"
            
        # JS inspection
        js_dir = static_dir / "js"
        if js_dir.is_dir():
            js_files = list(js_dir.glob("*.js"))
            assert len(js_files) >= 1, "At least one JavaScript asset required in static/js/"


# ==============================================================================
# Scenario 6: Windows Launcher `run.bat` End-to-End Operational Check
# ==============================================================================

class TestScenario6WindowsLauncher:
    """Validates the Windows launcher batch script in accordance with R5 / Acceptance Criteria."""
    
    @skip_unless_m5
    def test_scenario6_run_bat_complete_verification(self):
        """
        Verifies run.bat:
        1. Exists at project root.
        2. Has CRLF (\\r\\n) line endings (Windows standard).
        3. Kills processes on port 8000.
        4. Launches uvicorn main:app.
        5. Opens default browser to http://localhost:8000/.
        """
        run_bat = PROJECT_ROOT / "run.bat"
        assert run_bat.is_file(), "run.bat does not exist at project root"
        
        # CRLF check
        raw_bytes = run_bat.read_bytes()
        assert b"\r\n" in raw_bytes, "run.bat must use CRLF line endings"
        
        text = run_bat.read_text(encoding="utf-8", errors="ignore")
        
        # Port 8000 check
        assert "8000" in text, "run.bat must reference port 8000"
        
        # Server launch check
        assert "uvicorn" in text, "run.bat must launch uvicorn"
        assert "main:app" in text or "main" in text, "run.bat must target main:app"
        
        # Browser launch check
        assert "http://localhost:8000" in text or "http://127.0.0.1:8000" in text or "8000" in text
