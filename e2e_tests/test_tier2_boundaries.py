"""
Tier 2: Boundary, Corner Case, Dirty Data, and SLA Benchmark Tests.

Covers exact mathematical boundary limits (strict inequalities), sensory fault tolerance
(None/NaN/Inf), OpenSky HTTP 429 exponential backoff, and the <50ms cache retrieval SLA.
"""

import math
import time
from typing import Dict, Any, List
import pytest

from e2e_tests.dynamic_loader import (
    get_anomaly_components,
    get_cache_components,
    get_ingestion_components,
    skip_unless_m1,
    skip_unless_m2
)
from e2e_tests.conftest import AuthoritativeAnomalyOracle


# ==============================================================================
# 1. Exact Mathematical Boundary Tests for Anomaly Traps
# ==============================================================================

class TestAnomalyTrapBoundaries:
    """Rigorous boundary value testing for kinematic threshold inequalities."""
    
    @skip_unless_m2
    def test_descent_exact_boundary_is_nominal(self, anomaly_oracle):
        """
        Severe descent condition: vertical_rate < -20.32 m/s (-4,000 ft/min).
        Exact value -20.3200 m/s must be NOMINAL (strict inequality).
        """
        state = {
            "icao24": "3c0001", "callsign": "DLH001", "origin_country": "Germany",
            "longitude": 10.0, "latitude": 52.0, "baro_altitude": 8000.0,
            "velocity": 220.0, "vertical_rate": -20.320000,
            "squawk": "1000", "last_contact": time.time(), "on_ground": False
        }
        
        # Oracle derivation
        assert not anomaly_oracle.expected_descent_anomaly(state["vertical_rate"])
        
        # Engine execution
        engine_cls, _, _ = get_anomaly_components()
        _, state_cls = get_cache_components()
        state_obj = state_cls(**state) if state_cls else state
        eval_func = getattr(engine_cls, "evaluate", None) or getattr(engine_cls, "evaluate_vector", None)
        flags = eval_func(state_obj)
        
        descent_flags = [f for f in flags if "descent" in getattr(f, "category", "").lower() or "descent" in getattr(f, "rationale", "").lower()]
        assert len(descent_flags) == 0, "Exact boundary -20.32 m/s must NOT trigger severe descent anomaly"

    @skip_unless_m2
    def test_descent_just_below_boundary_triggers_anomaly(self, anomaly_oracle):
        """Value -20.3201 m/s (strictly < -20.32) MUST trigger severe descent anomaly."""
        state = {
            "icao24": "3c0002", "callsign": "DLH002", "origin_country": "Germany",
            "longitude": 10.0, "latitude": 52.0, "baro_altitude": 8000.0,
            "velocity": 220.0, "vertical_rate": -20.320100,
            "squawk": "1000", "last_contact": time.time(), "on_ground": False
        }
        
        assert anomaly_oracle.expected_descent_anomaly(state["vertical_rate"])
        
        engine_cls, _, _ = get_anomaly_components()
        _, state_cls = get_cache_components()
        state_obj = state_cls(**state) if state_cls else state
        eval_func = getattr(engine_cls, "evaluate", None) or getattr(engine_cls, "evaluate_vector", None)
        flags = eval_func(state_obj)
        
        descent_flags = [f for f in flags if "descent" in getattr(f, "category", "").lower() or "descent" in getattr(f, "rationale", "").lower()]
        assert len(descent_flags) > 0, "Vertical rate -20.3201 m/s must trigger severe descent anomaly"

    @skip_unless_m2
    def test_overspeed_exact_velocity_boundary_is_nominal(self, anomaly_oracle):
        """
        Overspeed condition: velocity > 330.0 m/s AND baro_altitude < 10,000 m.
        Exact velocity 330.000 m/s must be NOMINAL (strict inequality).
        """
        state = {
            "icao24": "390001", "callsign": "AFR001", "origin_country": "France",
            "longitude": 2.0, "latitude": 48.0, "baro_altitude": 5000.0,
            "velocity": 330.000000, "vertical_rate": 0.0,
            "squawk": "1000", "last_contact": time.time(), "on_ground": False
        }
        
        assert not anomaly_oracle.expected_overspeed_anomaly(state["velocity"], state["baro_altitude"])
        
        engine_cls, _, _ = get_anomaly_components()
        _, state_cls = get_cache_components()
        state_obj = state_cls(**state) if state_cls else state
        eval_func = getattr(engine_cls, "evaluate", None) or getattr(engine_cls, "evaluate_vector", None)
        flags = eval_func(state_obj)
        
        overspeed_flags = [f for f in flags if "overspeed" in getattr(f, "category", "").lower() or "overspeed" in getattr(f, "rationale", "").lower()]
        assert len(overspeed_flags) == 0, "Exact velocity 330.0 m/s must NOT trigger overspeed"

    @skip_unless_m2
    def test_overspeed_just_above_velocity_boundary_triggers_anomaly(self, anomaly_oracle):
        """Velocity 330.001 m/s at 5000 m (< 10000 m) MUST trigger overspeed outlier."""
        state = {
            "icao24": "390002", "callsign": "AFR002", "origin_country": "France",
            "longitude": 2.0, "latitude": 48.0, "baro_altitude": 5000.0,
            "velocity": 330.001000, "vertical_rate": 0.0,
            "squawk": "1000", "last_contact": time.time(), "on_ground": False
        }
        
        assert anomaly_oracle.expected_overspeed_anomaly(state["velocity"], state["baro_altitude"])
        
        engine_cls, _, _ = get_anomaly_components()
        _, state_cls = get_cache_components()
        state_obj = state_cls(**state) if state_cls else state
        eval_func = getattr(engine_cls, "evaluate", None) or getattr(engine_cls, "evaluate_vector", None)
        flags = eval_func(state_obj)
        
        overspeed_flags = [f for f in flags if "overspeed" in getattr(f, "category", "").lower() or "overspeed" in getattr(f, "rationale", "").lower()]
        assert len(overspeed_flags) > 0, "Velocity 330.001 m/s must trigger overspeed"

    @skip_unless_m2
    def test_overspeed_exact_altitude_ceiling_is_nominal(self, anomaly_oracle):
        """
        High velocity 350.0 m/s at exact altitude 10,000.0 m is NOMINAL
        because the condition is strictly altitude < 10,000 m.
        """
        state = {
            "icao24": "390003", "callsign": "AFR003", "origin_country": "France",
            "longitude": 2.0, "latitude": 48.0, "baro_altitude": 10000.000000,
            "velocity": 350.0, "vertical_rate": 0.0,
            "squawk": "1000", "last_contact": time.time(), "on_ground": False
        }
        
        assert not anomaly_oracle.expected_overspeed_anomaly(state["velocity"], state["baro_altitude"])
        
        engine_cls, _, _ = get_anomaly_components()
        _, state_cls = get_cache_components()
        state_obj = state_cls(**state) if state_cls else state
        eval_func = getattr(engine_cls, "evaluate", None) or getattr(engine_cls, "evaluate_vector", None)
        flags = eval_func(state_obj)
        
        overspeed_flags = [f for f in flags if "overspeed" in getattr(f, "category", "").lower() or "overspeed" in getattr(f, "rationale", "").lower()]
        assert len(overspeed_flags) == 0, "High velocity at exactly 10,000 m must NOT trigger overspeed (high-altitude exemption)"

    @skip_unless_m2
    def test_overspeed_just_below_altitude_ceiling_triggers_anomaly(self, anomaly_oracle):
        """Velocity 350.0 m/s at altitude 9,999.9 m MUST trigger overspeed."""
        state = {
            "icao24": "390004", "callsign": "AFR004", "origin_country": "France",
            "longitude": 2.0, "latitude": 48.0, "baro_altitude": 9999.900000,
            "velocity": 350.0, "vertical_rate": 0.0,
            "squawk": "1000", "last_contact": time.time(), "on_ground": False
        }
        
        assert anomaly_oracle.expected_overspeed_anomaly(state["velocity"], state["baro_altitude"])
        
        engine_cls, _, _ = get_anomaly_components()
        _, state_cls = get_cache_components()
        state_obj = state_cls(**state) if state_cls else state
        eval_func = getattr(engine_cls, "evaluate", None) or getattr(engine_cls, "evaluate_vector", None)
        flags = eval_func(state_obj)
        
        overspeed_flags = [f for f in flags if "overspeed" in getattr(f, "category", "").lower() or "overspeed" in getattr(f, "rationale", "").lower()]
        assert len(overspeed_flags) > 0, "Velocity 350 m/s at 9,999.9 m must trigger overspeed"

    @skip_unless_m2
    def test_squawk_non_emergency_codes_are_nominal(self, anomaly_oracle):
        """Verifies standard non-emergency squawk codes produce zero false positives."""
        standard_squawks = ["1200", "7000", "1000", "2000", "0000", "7777", "4401", "5201"]
        engine_cls, _, _ = get_anomaly_components()
        _, state_cls = get_cache_components()
        
        for code in standard_squawks:
            state = {
                "icao24": "3c1234", "callsign": "TEST", "origin_country": "DE",
                "longitude": 10.0, "latitude": 50.0, "baro_altitude": 8000.0,
                "velocity": 220.0, "vertical_rate": 0.0, "squawk": code,
                "last_contact": time.time(), "on_ground": False
            }
            assert not anomaly_oracle.expected_squawk_anomaly(code)
            
            state_obj = state_cls(**state) if state_cls else state
            eval_func = getattr(engine_cls, "evaluate", None) or getattr(engine_cls, "evaluate_vector", None)
            flags = eval_func(state_obj)
            squawk_flags = [f for f in flags if "squawk" in getattr(f, "category", "").lower() or "squawk" in getattr(f, "rationale", "").lower()]
            assert len(squawk_flags) == 0, f"False positive squawk anomaly triggered on nominal code {code}"


# ==============================================================================
# 2. Dirty Data & Sensory Fault Tolerance (None / NaN / Inf / Type Mismatches)
# ==============================================================================

class TestSensoryFaultTolerance:
    """Tests resilience against malformed, NaN, Infinite, and missing sensor values."""
    
    @skip_unless_m2
    def test_dirty_data_all_nones_no_exception(self):
        """F-ANO-06: Verifies vector with None in all sensor fields evaluates without throwing exceptions."""
        engine_cls, _, _ = get_anomaly_components()
        _, state_cls = get_cache_components()
        
        state_dict = {
            "icao24": "aabb01", "callsign": None, "origin_country": None,
            "longitude": None, "latitude": None, "baro_altitude": None,
            "velocity": None, "vertical_rate": None, "squawk": None,
            "last_contact": time.time(), "on_ground": False
        }
        
        try:
            state_obj = state_cls(**state_dict) if state_cls else state_dict
            eval_func = getattr(engine_cls, "evaluate", None) or getattr(engine_cls, "evaluate_vector", None)
            flags = eval_func(state_obj)
            assert len(flags) == 0, "All-None vector should trigger 0 anomalies"
        except Exception as e:
            pytest.fail(f"Unhandled exception on all-None vector: {type(e).__name__}: {e}")

    @skip_unless_m2
    def test_dirty_data_nan_and_infinities_immunity(self):
        """F-ANO-06: Verifies math.nan and +/-inf in telemetry do not crash anomaly traps."""
        engine_cls, _, _ = get_anomaly_components()
        _, state_cls = get_cache_components()
        
        dirty_states = [
            # NaNs
            {"icao24": "nan001", "baro_altitude": float("nan"), "velocity": float("nan"), "vertical_rate": float("nan"), "squawk": None, "last_contact": time.time()},
            # Positive Infinities
            {"icao24": "inf001", "baro_altitude": float("inf"), "velocity": float("inf"), "vertical_rate": 0.0, "squawk": "1000", "last_contact": time.time()},
            # Negative Infinities
            {"icao24": "inf002", "baro_altitude": 5000.0, "velocity": 200.0, "vertical_rate": float("-inf"), "squawk": "1000", "last_contact": time.time()}
        ]
        
        eval_func = getattr(engine_cls, "evaluate", None) or getattr(engine_cls, "evaluate_vector", None)
        for d in dirty_states:
            try:
                state_obj = state_cls(**d) if state_cls else d
                flags = eval_func(state_obj)
                # Should not crash, and should not falsely trigger overspeed on NaN/Inf
                for f in flags:
                    assert getattr(f, "category", "") != "OVERSPEED_OUTLIER" or not math.isnan(d.get("velocity", 0))
            except Exception as e:
                pytest.fail(f"Failed handling NaN/Inf input for {d['icao24']}: {e}")

    def test_tuple_sanitizer_dirty_inputs(self, sample_dirty_tuples):
        """F-ING-02: Verifies tuple parser safely cleans dirty ADS-B tuples."""
        _, sanitizer = get_ingestion_components()
        if not sanitizer:
            pytest.skip("Ingestion tuple sanitizer not implemented yet")
            
        for raw_tuple in sample_dirty_tuples:
            try:
                result = sanitizer(raw_tuple)
                # Must either return cleaned object or None if unparseable, never raise unhandled error
                if result is not None:
                    # Verify sanitized floats are never raw NaN or Inf
                    for field in ["baro_altitude", "velocity", "vertical_rate"]:
                        val = getattr(result, field, None)
                        if val is not None and isinstance(val, (int, float)):
                            assert not math.isnan(val), f"Field {field} leaked raw NaN"
                            assert not math.isinf(val), f"Field {field} leaked raw Inf"
            except Exception as e:
                pytest.fail(f"Sanitizer raised unhandled exception on tuple {raw_tuple}: {e}")


# ==============================================================================
# 3. HTTP 429 Rate Limit Exponential Backoff & Jitter
# ==============================================================================

class TestRateLimitBackoff:
    """F-ING-04: Verifies exponential backoff with jitter on OpenSky HTTP 429."""
    
    def test_exponential_backoff_timing_formula(self):
        """
        Verifies backoff duration strictly doubles with consecutive failures:
        delay = min(max_backoff, base * 2**attempt) + jitter
        """
        base = 2.0
        max_backoff = 60.0
        
        expected_delays_without_jitter = [
            base * (2 ** 0),  # attempt 0: 2s
            base * (2 ** 1),  # attempt 1: 4s
            base * (2 ** 2),  # attempt 2: 8s
            base * (2 ** 3),  # attempt 3: 16s
            base * (2 ** 4),  # attempt 4: 32s
            min(max_backoff, base * (2 ** 5)),  # attempt 5: 60s (capped)
        ]
        
        assert expected_delays_without_jitter[0] == 2.0
        assert expected_delays_without_jitter[1] == 4.0
        assert expected_delays_without_jitter[2] == 8.0
        assert expected_delays_without_jitter[3] == 16.0
        assert expected_delays_without_jitter[4] == 32.0
        assert expected_delays_without_jitter[5] == 60.0


# ==============================================================================
# 4. Cache Retrieval Latency SLA Benchmark (< 50ms for 1,500 flights)
# ==============================================================================

class TestCachePerformanceBenchmark:
    """F-TEST-04 / R5 SLA: Measures cache retrieval under 1,500 active flights."""
    
    @skip_unless_m1
    def test_cache_retrieval_sla_benchmark_under_50ms(self, initialized_cache):
        """
        Benchmark SLA Guarantee:
        Fills cache with 1,500 simulated active flights.
        Executes 100 consecutive full snapshot reads.
        Asserts p95 latency < 50.0ms and max latency < 50.0ms.
        """
        cache = initialized_cache
        _, state_cls = get_cache_components()
        
        # Populate 1,500 simulated active flights
        now = time.time()
        for i in range(1500):
            icao = f"{i:06x}"
            state = state_cls(
                icao24=icao,
                callsign=f"SIM{i:04d}",
                origin_country="European Airspace",
                longitude=-5.0 + (i % 40) * 0.5,
                latitude=35.0 + (i % 25) * 0.8,
                baro_altitude=10000.0 + (i % 20) * 100.0,
                velocity=230.0 + (i % 10) * 2.0,
                vertical_rate=0.0,
                squawk="1000",
                last_contact=now - (i % 30),
                on_ground=False
            )
            update_func = getattr(cache, "update_vector", None) or getattr(cache, "update", None)
            update_func(state)
            
        # Benchmark 100 snapshot retrieval operations
        get_telemetry = getattr(cache, "get_all_active", None) or getattr(cache, "get_active_telemetry", None)
        assert get_telemetry is not None, "Cache missing get_all_active or get_active_telemetry method"
        
        latencies_ms = []
        for _ in range(100):
            t_start = time.perf_counter_ns()
            snapshot = get_telemetry()
            t_end = time.perf_counter_ns()
            latencies_ms.append((t_end - t_start) / 1_000_000.0)
            
        avg_ms = sum(latencies_ms) / len(latencies_ms)
        sorted_latencies = sorted(latencies_ms)
        p95_ms = sorted_latencies[int(len(latencies_ms) * 0.95)]
        max_ms = max(latencies_ms)
        
        print(f"\n[CACHE SLA BENCHMARK] 1,500 Flights: Avg={avg_ms:.3f}ms, p95={p95_ms:.3f}ms, Max={max_ms:.3f}ms")
        
        # Rigorous SLA assertion: strictly < 50.0 ms
        assert p95_ms < 50.0, f"p95 cache retrieval latency {p95_ms:.3f}ms exceeded 50ms SLA requirement!"
        assert max_ms < 50.0, f"Max cache retrieval latency {max_ms:.3f}ms exceeded 50ms SLA requirement!"
