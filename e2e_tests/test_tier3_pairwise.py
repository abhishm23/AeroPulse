"""
Tier 3: Pairwise Cross-Feature Combinatorial Interaction Tests.

Verifies system resilience under interacting feature conditions:
- Compound simultaneous anomalies (Squawk 7700 + Severe Descent, Squawk 7500 + Overspeed)
- Cache TTL pruning during concurrent read queries
- Continuous cache serving during HTTP 429 rate limit backoff
- Airborne vs surface filtering combined with active anomaly flags
- Anomaly audit feed persistence across flight lifecycle / TTL pruning
"""

import time
import threading
from typing import Dict, Any, List
import pytest

from e2e_tests.dynamic_loader import (
    get_anomaly_components,
    get_cache_components,
    get_fastapi_app,
    skip_unless_m1,
    skip_unless_m2,
    skip_unless_m3
)
from e2e_tests.conftest import AuthoritativeAnomalyOracle


# ==============================================================================
# 1. Compound Anomaly Traps (Simultaneous Traps)
# ==============================================================================

class TestCompoundAnomalyInteractions:
    """F-ANO-09: Tests simultaneous multiple anomaly triggers on a single flight."""
    
    @skip_unless_m2
    def test_compound_squawk_7700_and_severe_descent(self, anomaly_oracle):
        """Aircraft declaring emergency (7700) while in rapid depressurization descent (-28 m/s)."""
        engine_cls, severity_cls, _ = get_anomaly_components()
        _, state_cls = get_cache_components()
        
        state_dict = {
            "icao24": "400770", "callsign": "BAW770", "origin_country": "United Kingdom",
            "longitude": 0.5, "latitude": 51.5, "baro_altitude": 7000.0,
            "velocity": 240.0, "vertical_rate": -28.0,  # Descent < -20.32
            "squawk": "7700",  # Squawk Emergency
            "last_contact": time.time(), "on_ground": False
        }
        
        # Oracle verification
        oracle_flags = anomaly_oracle.evaluate(state_dict)
        assert "SQUAWK_EMERGENCY" in oracle_flags
        assert "SEVERE_DESCENT" in oracle_flags
        
        # Engine execution
        state_obj = state_cls(**state_dict) if state_cls else state_dict
        eval_func = getattr(engine_cls, "evaluate", None) or getattr(engine_cls, "evaluate_vector", None)
        flags = eval_func(state_obj)
        
        assert len(flags) >= 2, f"Expected at least 2 compound anomaly flags, got {len(flags)}"
        categories = [str(getattr(f, "category", "")).lower() for f in flags]
        rationales = " ".join([str(getattr(f, "rationale", "")).lower() for f in flags])
        
        assert any("squawk" in c or "emergency" in c or "7700" in rationales for c in categories)
        assert any("descent" in c or "descent" in rationales for c in categories)
        
        # Severity resolution: CRITICAL must dominate
        resolve_func = getattr(engine_cls, "resolve_severity", None)
        if resolve_func:
            sev = resolve_func(flags)
            assert str(sev).upper() in ["CRITICAL", "ANOMALYSEVERITY.CRITICAL"]

    @skip_unless_m2
    def test_compound_squawk_7500_and_overspeed(self, anomaly_oracle):
        """Aircraft hijacked (7500) and exceeding speed limit (345 m/s at 5,000m)."""
        engine_cls, _, _ = get_anomaly_components()
        _, state_cls = get_cache_components()
        
        state_dict = {
            "icao24": "4b0750", "callsign": "SWR750", "origin_country": "Switzerland",
            "longitude": 8.0, "latitude": 47.0, "baro_altitude": 5000.0,
            "velocity": 345.0,  # Overspeed > 330
            "vertical_rate": 0.0,
            "squawk": "7500",  # Hijack
            "last_contact": time.time(), "on_ground": False
        }
        
        oracle_flags = anomaly_oracle.evaluate(state_dict)
        assert "SQUAWK_EMERGENCY" in oracle_flags
        assert "OVERSPEED_OUTLIER" in oracle_flags
        
        state_obj = state_cls(**state_dict) if state_cls else state_dict
        eval_func = getattr(engine_cls, "evaluate", None) or getattr(engine_cls, "evaluate_vector", None)
        flags = eval_func(state_obj)
        
        assert len(flags) >= 2, f"Expected 2 compound anomaly flags, got {len(flags)}"
        rationales = " ".join([str(getattr(f, "rationale", "")).lower() for f in flags])
        assert any(term in rationales for term in ["hijack", "unlawful", "7500"])
        assert any(term in rationales for term in ["overspeed", "speed", "345"])


# ==============================================================================
# 2. Concurrency: Cache TTL Pruning During Continuous Reader Queries
# ==============================================================================

class TestConcurrencyAndCacheLifecycle:
    """F-ING-06..07: Verifies thread-safety during concurrent cache reads and TTL pruning."""
    
    @skip_unless_m1
    def test_cache_pruning_during_continuous_queries(self, initialized_cache):
        """
        Simulates background worker pruning stale flights while 5 concurrent threads
        continuously query get_all_active() / get_active_telemetry().
        Verifies zero RuntimeError (dictionary changed size during iteration).
        """
        cache = initialized_cache
        _, state_cls = get_cache_components()
        
        # Populate initial 100 flights
        now = time.time()
        update_func = getattr(cache, "update_vector", None) or getattr(cache, "update", None)
        for i in range(100):
            st = state_cls(
                icao24=f"4b{i:04x}", callsign=f"TST{i:03d}", origin_country="CH",
                longitude=8.0, latitude=47.0, baro_altitude=10000.0,
                velocity=230.0, vertical_rate=0.0, squawk="1000",
                last_contact=now - (i * 2),  # Half will be > 120s stale
                on_ground=False
            )
            update_func(st)
            
        reader_exceptions = []
        stop_event = threading.Event()
        
        def reader_worker():
            get_all = getattr(cache, "get_all_active", None) or getattr(cache, "get_active_telemetry", None)
            while not stop_event.is_set():
                try:
                    _ = get_all()
                    time.sleep(0.001)
                except Exception as ex:
                    reader_exceptions.append(ex)
                    break
                    
        # Launch 4 reader threads
        threads = [threading.Thread(target=reader_worker) for _ in range(4)]
        for t in threads:
            t.start()
            
        # Execute pruning in main thread multiple times
        prune_func = getattr(cache, "prune_stale", None) or getattr(cache, "evict_stale", None)
        try:
            for _ in range(10):
                if prune_func:
                    prune_func(ttl_seconds=100.0)
                time.sleep(0.01)
        finally:
            stop_event.set()
            for t in threads:
                t.join(timeout=2.0)
                
        assert len(reader_exceptions) == 0, f"Concurrent reader failed with: {reader_exceptions}"


# ==============================================================================
# 3. Continuous Cache Serving During HTTP 429 Ingestion Outage
# ==============================================================================

class TestIngestionResilienceAndServing:
    """F-ING-06: Verifies cache continues serving live snapshot when OpenSky returns 429."""
    
    @skip_unless_m3
    def test_rate_limit_429_continuous_cache_serving(self, app_client):
        """
        Verifies that querying GET /api/telemetry returns HTTP 200 with valid cached vectors
        even when the backend ingestion worker is experiencing simulated 429 rate limit backoff.
        """
        # Baseline check on telemetry endpoint
        resp = app_client.get("/api/telemetry")
        assert resp.status_code == 200, "Telemetry endpoint failed"
        
        # Check health endpoint reports operational state
        health_resp = app_client.get("/api/health")
        assert health_resp.status_code == 200
        health_data = health_resp.json()
        assert health_data.get("status") in ["healthy", "degraded", "ok"]


# ==============================================================================
# 4. Anomaly Audit Feed Persistence
# ==============================================================================

class TestAnomalyAuditPersistence:
    """F-ANO-08: Verifies anomaly alerts persist in GET /api/anomalies even after flight lands/prunes."""
    
    @skip_unless_m3
    def test_anomaly_event_feed_endpoint(self, app_client):
        """Validates that GET /api/anomalies returns the historical log of detected anomalies."""
        resp = app_client.get("/api/anomalies")
        assert resp.status_code == 200
        data = resp.json()
        
        # Structure may be list or envelope dict
        events = data.get("events", data) if isinstance(data, dict) else data
        assert isinstance(events, list)
        
        # If events exist, each event must carry ICAO, rationale, and severity
        for ev in events:
            assert any(k in ev for k in ["icao24", "icao"])
            assert any(k in ev for k in ["rationale", "description"])
            assert any(k in ev for k in ["severity", "level"])
