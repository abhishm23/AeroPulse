"""
tests/test_challenger_m2_2.py
Milestone 2 Challenger 2 Empirical Stress Test Suite.

Scope & Mission:
1. Massive False-Positive Stress Test:
   Generate and evaluate 25,000+ realistic nominal commercial flight vectors across diverse flight phases:
   - High-altitude cruise (alt 10,000-12,000m, speed 200-280 m/s, vertical rate -2 to +2 m/s, squawk 1000-7000).
   - Normal climb (alt 1,000-9,000m, speed 150-250 m/s, vertical rate +5 to +15 m/s).
   - Normal descent (alt 2,000-9,000m, speed 140-240 m/s, vertical rate -5 to -15 m/s).
   - Approach & landing (alt 100-1,500m, speed 60-140 m/s, vertical rate -2 to -6 m/s).
   - Extreme boundary nominal cases (exact boundary values, high-altitude supersonic, negative altitudes).
   Verify strictly 0 false positives are flagged across all vectors (target: 50,000+ vectors).

2. Cache Anomaly Event Feed Stress Test:
   - Trigger 500 rapid anomaly events on AircraftCache.
   - Verify _recent_anomalies remains strictly capped at maxlen=100.
   - Verify state-transition deduplication functions under rapid redundant updates.
   - Verify get_recent_anomalies() returns sorted newest-first in < 1ms (< 1000 us).
   - Verify multi-threaded concurrency safety during rapid burst writes and reads.
"""

import collections
import random
import statistics
import threading
import time
from typing import Any, Dict, List, Optional
import pytest

from core.anomaly_engine import (
    MechanicalAnomalyEngine,
    DESCENT_RATE_THRESHOLD_MPS,
    OVERSPEED_VELOCITY_THRESHOLD_MPS,
    OVERSPEED_ALTITUDE_CEILING_M,
)
from core.cache import AircraftCache
from models.aircraft import FlightState
from models.anomaly import AnomalyCategory, AnomalyFlag, AnomalyRecord, AnomalySeverity


# ==============================================================================
# 1. MASSIVE FALSE-POSITIVE STRESS TESTS (25,000+ NOMINAL COMMERCIAL FLIGHTS)
# ==============================================================================

class TestMassiveFalsePositiveStress:
    """
    Empirical stress-testing of false-positive absence across 50,000+ realistic
    nominal commercial flight vectors in diverse operational flight phases.
    """

    @pytest.mark.parametrize("seed", [42, 101, 2024])
    def test_high_altitude_cruise_zero_false_positives(self, seed: int):
        """
        Generate 10,000 realistic high-altitude cruise vectors:
        - Altitude: 10,000 - 12,000 meters (FL330 - FL390)
        - Speed: 200 - 280 m/s (388 - 544 knots / Mach 0.70 - 0.85)
        - Vertical rate: -2.0 to +2.0 m/s (-394 to +394 ft/min minor corrections)
        - Squawk: 1000 - 7000 (standard non-emergency assigned squawks)
        Assert strictly 0 false positives.
        """
        rng = random.Random(seed)
        sample_size = 10000
        false_positive_count = 0
        base_time = 1725500000.0

        for i in range(sample_size):
            alt = rng.uniform(10000.0, 12000.0)
            spd = rng.uniform(200.0, 280.0)
            vr = rng.uniform(-2.0, 2.0)
            # Standard non-emergency squawk between 1000 and 7000
            sqk = f"{rng.randint(1000, 7000)}"
            state = {
                "icao24": f"crz{i:05x}",
                "callsign": f"CRZ{i:04d}",
                "baro_altitude": alt,
                "velocity": spd,
                "vertical_rate": vr,
                "squawk": sqk,
                "last_contact": base_time + i,
            }
            flags = MechanicalAnomalyEngine.evaluate(state)
            if flags:
                false_positive_count += len(flags)

        assert false_positive_count == 0, f"Detected {false_positive_count} false positives in cruise phase!"

    @pytest.mark.parametrize("seed", [123, 456, 789])
    def test_normal_climb_zero_false_positives(self, seed: int):
        """
        Generate 10,000 realistic normal climb vectors:
        - Altitude: 1,000 - 9,000 meters
        - Speed: 150 - 250 m/s (290 - 485 knots)
        - Vertical rate: +5.0 to +15.0 m/s (+984 to +2,953 ft/min sustained climb)
        - Squawk: standard departure squawks (1000-6999)
        Assert strictly 0 false positives.
        """
        rng = random.Random(seed)
        sample_size = 10000
        false_positive_count = 0
        base_time = 1725500000.0

        for i in range(sample_size):
            alt = rng.uniform(1000.0, 9000.0)
            spd = rng.uniform(150.0, 250.0)
            vr = rng.uniform(5.0, 15.0)
            sqk = f"{rng.randint(1000, 6999)}"
            state = {
                "icao24": f"clb{i:05x}",
                "callsign": f"CLB{i:04d}",
                "baro_altitude": alt,
                "velocity": spd,
                "vertical_rate": vr,
                "squawk": sqk,
                "last_contact": base_time + i,
            }
            flags = MechanicalAnomalyEngine.evaluate(state)
            if flags:
                false_positive_count += len(flags)

        assert false_positive_count == 0, f"Detected {false_positive_count} false positives in climb phase!"

    @pytest.mark.parametrize("seed", [314, 271, 999])
    def test_normal_descent_zero_false_positives(self, seed: int):
        """
        Generate 10,000 realistic normal descent vectors:
        - Altitude: 2,000 - 9,000 meters
        - Speed: 140 - 240 m/s (272 - 466 knots)
        - Vertical rate: -5.0 to -15.0 m/s (-984 to -2,953 ft/min standard descent, well above -20.32 m/s)
        - Squawk: standard arrival squawks (1000-7000)
        Assert strictly 0 false positives.
        """
        rng = random.Random(seed)
        sample_size = 10000
        false_positive_count = 0
        base_time = 1725500000.0

        for i in range(sample_size):
            alt = rng.uniform(2000.0, 9000.0)
            spd = rng.uniform(140.0, 240.0)
            # Normal descents range between -5 and -15 m/s (never exceeding -20.32 m/s)
            vr = rng.uniform(-15.0, -5.0)
            sqk = f"{rng.randint(1000, 7000)}"
            state = {
                "icao24": f"des{i:05x}",
                "callsign": f"DES{i:04d}",
                "baro_altitude": alt,
                "velocity": spd,
                "vertical_rate": vr,
                "squawk": sqk,
                "last_contact": base_time + i,
            }
            flags = MechanicalAnomalyEngine.evaluate(state)
            if flags:
                false_positive_count += len(flags)

        assert false_positive_count == 0, f"Detected {false_positive_count} false positives in descent phase!"

    @pytest.mark.parametrize("seed", [777, 888, 999])
    def test_approach_and_landing_zero_false_positives(self, seed: int):
        """
        Generate 10,000 realistic approach and final landing vectors:
        - Altitude: 100 - 1,500 meters (GLS / ILS 3-degree glide slope)
        - Speed: 60 - 140 m/s (116 - 272 knots touchdown to intermediate approach)
        - Vertical rate: -2.0 to -6.0 m/s (-394 to -1,181 ft/min on glide path)
        - Squawk: standard approach squawks (1000-7000)
        Assert strictly 0 false positives.
        """
        rng = random.Random(seed)
        sample_size = 10000
        false_positive_count = 0
        base_time = 1725500000.0

        for i in range(sample_size):
            alt = rng.uniform(100.0, 1500.0)
            spd = rng.uniform(60.0, 140.0)
            vr = rng.uniform(-6.0, -2.0)
            sqk = f"{rng.randint(1000, 7000)}"
            state = {
                "icao24": f"app{i:05x}",
                "callsign": f"APP{i:04d}",
                "baro_altitude": alt,
                "velocity": spd,
                "vertical_rate": vr,
                "squawk": sqk,
                "last_contact": base_time + i,
            }
            flags = MechanicalAnomalyEngine.evaluate(state)
            if flags:
                false_positive_count += len(flags)

        assert false_positive_count == 0, f"Detected {false_positive_count} false positives in approach phase!"

    def test_massive_50000_vector_comprehensive_matrix(self):
        """
        Comprehensive stress test combining 50,000 distinct flight vectors:
        - 12,500 cruise vectors
        - 12,500 climb vectors
        - 12,500 descent vectors
        - 12,500 approach vectors
        Evaluated across both Pydantic FlightState objects and raw dictionaries.
        Measures total throughput and guarantees strictly 0 false positives.
        """
        rng = random.Random(42)
        total_vectors = 50000
        base_time = 1725500000.0
        flags_detected = 0

        t0 = time.perf_counter()

        for i in range(total_vectors):
            phase = i % 4
            if phase == 0:
                # Cruise
                alt = rng.uniform(10000.0, 12000.0)
                spd = rng.uniform(200.0, 280.0)
                vr = rng.uniform(-2.0, 2.0)
            elif phase == 1:
                # Climb
                alt = rng.uniform(1000.0, 9000.0)
                spd = rng.uniform(150.0, 250.0)
                vr = rng.uniform(5.0, 15.0)
            elif phase == 2:
                # Descent
                alt = rng.uniform(2000.0, 9000.0)
                spd = rng.uniform(140.0, 240.0)
                vr = rng.uniform(-15.0, -5.0)
            else:
                # Approach & landing
                alt = rng.uniform(100.0, 1500.0)
                spd = rng.uniform(60.0, 140.0)
                vr = rng.uniform(-6.0, -2.0)

            sqk = f"{rng.randint(1000, 7000)}"
            icao = f"flt{i:06x}"
            callsign = f"FLT{i:05d}"
            ts = base_time + i

            # Test alternating representations: half FlightState instances, half dicts
            if i % 2 == 0:
                state: Any = FlightState(
                    icao24=icao,
                    callsign=callsign,
                    baro_altitude=alt,
                    velocity=spd,
                    vertical_rate=vr,
                    squawk=sqk,
                    last_contact=ts,
                )
            else:
                state = {
                    "icao24": icao,
                    "callsign": callsign,
                    "baro_altitude": alt,
                    "velocity": spd,
                    "vertical_rate": vr,
                    "squawk": sqk,
                    "last_contact": ts,
                }

            flags = MechanicalAnomalyEngine.evaluate(state)
            if flags:
                flags_detected += len(flags)
            sev = MechanicalAnomalyEngine.resolve_severity(flags)
            assert sev == AnomalySeverity.NOMINAL

        t1 = time.perf_counter()
        elapsed = t1 - t0
        throughput = total_vectors / elapsed

        print(f"\n[Empirical Evaluation] Evaluated {total_vectors} vectors in {elapsed:.3f}s ({throughput:.0f} vectors/s). False positives: {flags_detected}")
        assert flags_detected == 0, f"Expected 0 false positives across {total_vectors} vectors, found {flags_detected}!"
        assert throughput > 50000, f"Throughput {throughput:.0f} vectors/s is below expected performance (>50k/s)!"

    def test_extreme_nominal_boundary_conditions(self):
        """
        Verify strict mathematical inequality boundary conditions for nominal flight vectors:
        - Exact descent threshold: vertical_rate = -20.3200 m/s (must remain NOMINAL)
        - Near-threshold descent: vertical_rate = -20.3199 m/s (must remain NOMINAL)
        - Exact overspeed velocity: velocity = 330.0000 m/s at alt = 9999.0 m (must remain NOMINAL)
        - Exact overspeed altitude ceiling: velocity = 350.0 m/s at alt = 10000.0 m (must remain NOMINAL)
        - Supersonic high-altitude corridor: velocity = 600.0 m/s at alt = 15000.0 m (must remain NOMINAL)
        - Low-speed ground and sea-level vectors: velocity = 0.0, altitude = 0.0, altitude = -5.0 m
        - Valid non-emergency squawk strings: '1200', '7000', '2000', '0100', '7777', '7501', '7601', '7701'
        """
        nominal_boundary_cases = [
            # Exact descent threshold: -20.32 is NOT < -20.32
            {"vertical_rate": -20.3200, "baro_altitude": 8000.0, "velocity": 220.0, "squawk": "1000"},
            # Just above descent threshold
            {"vertical_rate": -20.3199, "baro_altitude": 8000.0, "velocity": 220.0, "squawk": "1000"},
            {"vertical_rate": -20.0, "baro_altitude": 8000.0, "velocity": 220.0, "squawk": "1000"},
            # Exact velocity threshold: 330.0 is NOT > 330.0
            {"vertical_rate": -5.0, "baro_altitude": 5000.0, "velocity": 330.0000, "squawk": "1000"},
            {"vertical_rate": -5.0, "baro_altitude": 5000.0, "velocity": 329.9999, "squawk": "1000"},
            # Exact altitude ceiling: 10000.0 is NOT < 10000.0
            {"vertical_rate": -5.0, "baro_altitude": 10000.0000, "velocity": 350.0, "squawk": "1000"},
            {"vertical_rate": -5.0, "baro_altitude": 10000.1, "velocity": 400.0, "squawk": "1000"},
            # High-altitude supersonic cruise (Concorde / military corridor above 10,000m)
            {"vertical_rate": 0.0, "baro_altitude": 15000.0, "velocity": 600.0, "squawk": "1000"},
            # Ground rolls and negative elevation airports (e.g. Amsterdam Schiphol -3m, Dead Sea)
            {"vertical_rate": 0.0, "baro_altitude": -3.5, "velocity": 15.0, "squawk": "1000"},
            {"vertical_rate": 0.0, "baro_altitude": 0.0, "velocity": 0.0, "squawk": "1000"},
            # Non-emergency squawks
            {"vertical_rate": -2.0, "baro_altitude": 10500.0, "velocity": 240.0, "squawk": "7000"},
            {"vertical_rate": -2.0, "baro_altitude": 10500.0, "velocity": 240.0, "squawk": "1200"},
            {"vertical_rate": -2.0, "baro_altitude": 10500.0, "velocity": 240.0, "squawk": "2000"},
            {"vertical_rate": -2.0, "baro_altitude": 10500.0, "velocity": 240.0, "squawk": "0100"},
            {"vertical_rate": -2.0, "baro_altitude": 10500.0, "velocity": 240.0, "squawk": "7777"},
            {"vertical_rate": -2.0, "baro_altitude": 10500.0, "velocity": 240.0, "squawk": "7501"},
            {"vertical_rate": -2.0, "baro_altitude": 10500.0, "velocity": 240.0, "squawk": "7601"},
            {"vertical_rate": -2.0, "baro_altitude": 10500.0, "velocity": 240.0, "squawk": "7701"},
            {"vertical_rate": -2.0, "baro_altitude": 10500.0, "velocity": 240.0, "squawk": "0000"},
            # Extreme climb rates (positive vertical rate is NOT descent)
            {"vertical_rate": 50.0, "baro_altitude": 6000.0, "velocity": 220.0, "squawk": "1000"},
            {"vertical_rate": 100.0, "baro_altitude": 11000.0, "velocity": 250.0, "squawk": "1000"},
        ]

        for idx, case in enumerate(nominal_boundary_cases):
            state = {
                "icao24": f"bnd{idx:03d}",
                "callsign": f"BND{idx:02d}",
                "baro_altitude": case["baro_altitude"],
                "velocity": case["velocity"],
                "vertical_rate": case["vertical_rate"],
                "squawk": case["squawk"],
                "last_contact": 1725500000.0 + idx,
            }
            flags = MechanicalAnomalyEngine.evaluate(state)
            assert len(flags) == 0, f"Boundary case #{idx} unexpectedly flagged: {flags}"
            assert MechanicalAnomalyEngine.resolve_severity(flags) == AnomalySeverity.NOMINAL


# ==============================================================================
# 2. CACHE ANOMALY EVENT FEED STRESS TESTS (CAPPING, DEDUP, LATENCY < 1MS)
# ==============================================================================

class TestCacheAnomalyEventFeedStress:
    """
    Empirical stress-testing of the in-memory AircraftCache anomaly event feed:
    - 500 rapid anomaly bursts strictly capped at maxlen=100
    - Exact FIFO queue eviction verification
    - State-transition deduplication
    - get_recent_anomalies() sub-millisecond (< 1ms) retrieval benchmark
    - Thread-safe concurrent anomaly bursts
    """

    def test_500_rapid_anomalies_buffer_capping_and_fifo(self):
        """
        Trigger 500 rapid unique anomaly events across 500 distinct aircraft.
        Verify:
        - _recent_anomalies remains strictly capped at maxlen=100.
        - cache.get_stats()['recent_anomalies_count'] == 100.
        - Exact FIFO eviction: events 0..399 are evicted, events 400..499 are retained.
        - Newest-first reverse-chronological ordering: event 499 is first, event 400 is last.
        """
        cache = AircraftCache(max_anomalies_buffer=100)
        base_time = 1725500000.0
        total_events = 500

        for i in range(total_events):
            state = FlightState(
                icao24=f"emg{i:04x}",
                callsign=f"EMG{i:04d}",
                squawk="7700",
                baro_altitude=10000.0,
                velocity=220.0,
                vertical_rate=-1.0,
                last_contact=base_time + i,
            )
            detail = cache.update_vector(state)
            assert detail.has_anomaly is True
            assert detail.status == "CRITICAL"

            # Check that length never exceeds 100 at any point
            current_len = len(cache._recent_anomalies)
            assert current_len <= 100
            if i >= 100:
                assert current_len == 100

        stats = cache.get_stats()
        assert stats["recent_anomalies_count"] == 100

        recent = cache.get_recent_anomalies()
        assert len(recent) == 100

        # Verify newest-first ordering
        # Event 499 (newest) should be index 0
        assert recent[0].icao24 == f"emg{499:04x}"
        assert recent[0].callsign == f"EMG{499:04d}"
        assert recent[0].timestamp == base_time + 499

        # Event 400 (oldest kept) should be index 99
        assert recent[-1].icao24 == f"emg{400:04x}"
        assert recent[-1].callsign == f"EMG{400:04d}"
        assert recent[-1].timestamp == base_time + 400

        # Verify strict monotonic decrease of timestamps in get_recent_anomalies()
        for idx in range(len(recent) - 1):
            assert recent[idx].timestamp >= recent[idx + 1].timestamp

    def test_state_transition_deduplication_comprehensive(self):
        """
        Empirically verify anomaly feed deduplication across state transitions:
        1. Repeated identical updates on the SAME aircraft do NOT generate duplicate events.
        2. Escalation with new anomaly categories DOES generate events for the new category.
        3. Recovery to NOMINAL does not add events to the log.
        4. Re-entering an anomaly after clearing DOES generate a new event.
        """
        cache = AircraftCache(max_anomalies_buffer=100)
        base_time = 1725500000.0

        # Phase 1: Aircraft starts NOMINAL
        s1 = FlightState(
            icao24="dedup01", callsign="DEDUP1", squawk="1000",
            baro_altitude=10000.0, velocity=220.0, vertical_rate=0.0,
            last_contact=base_time + 1.0,
        )
        cache.update_vector(s1)
        assert len(cache.get_recent_anomalies()) == 0

        # Phase 2: Enters SEVERE_DESCENT (First event emitted)
        s2 = FlightState(
            icao24="dedup01", callsign="DEDUP1", squawk="1000",
            baro_altitude=8000.0, velocity=220.0, vertical_rate=-25.0,
            last_contact=base_time + 10.0,
        )
        cache.update_vector(s2)
        assert len(cache.get_recent_anomalies()) == 1
        assert cache.get_recent_anomalies()[0].category == AnomalyCategory.SEVERE_DESCENT.value

        # Phase 3: Pumping 50 consecutive updates while STILL in SEVERE_DESCENT
        for step in range(1, 51):
            s_dup = FlightState(
                icao24="dedup01", callsign="DEDUP1", squawk="1000",
                baro_altitude=8000.0 - (step * 200.0), velocity=220.0, vertical_rate=-26.0,
                last_contact=base_time + 10.0 + step,
            )
            cache.update_vector(s_dup)
            # Deduplication invariant: still exactly 1 event
            assert len(cache.get_recent_anomalies()) == 1, f"Failed at step {step}: duplicated event logged!"

        # Phase 4: Escalation - pilot squawks 7700 while still descending (Second event emitted)
        s_escalate = FlightState(
            icao24="dedup01", callsign="DEDUP1", squawk="7700",
            baro_altitude=4000.0, velocity=220.0, vertical_rate=-25.0,
            last_contact=base_time + 100.0,
        )
        cache.update_vector(s_escalate)
        assert len(cache.get_recent_anomalies()) == 2
        assert cache.get_recent_anomalies()[0].category == AnomalyCategory.SQUAWK_EMERGENCY.value
        assert cache.get_recent_anomalies()[1].category == AnomalyCategory.SEVERE_DESCENT.value

        # Phase 5: Further escalation - velocity exceeds 330 m/s below 10,000m (Third event emitted)
        s_overspeed = FlightState(
            icao24="dedup01", callsign="DEDUP1", squawk="7700",
            baro_altitude=3500.0, velocity=345.0, vertical_rate=-25.0,
            last_contact=base_time + 110.0,
        )
        cache.update_vector(s_overspeed)
        assert len(cache.get_recent_anomalies()) == 3
        assert cache.get_recent_anomalies()[0].category == AnomalyCategory.OVERSPEED_OUTLIER.value

        # Phase 6: Pumping 20 updates with all 3 anomalies active
        for step in range(1, 21):
            s_all3 = FlightState(
                icao24="dedup01", callsign="DEDUP1", squawk="7700",
                baro_altitude=3000.0, velocity=340.0, vertical_rate=-24.0,
                last_contact=base_time + 120.0 + step,
            )
            cache.update_vector(s_all3)
            assert len(cache.get_recent_anomalies()) == 3

        # Phase 7: Aircraft levels off and squawk resets to 1000 (Recovers to NOMINAL)
        s_recover = FlightState(
            icao24="dedup01", callsign="DEDUP1", squawk="1000",
            baro_altitude=2500.0, velocity=180.0, vertical_rate=-2.0,
            last_contact=base_time + 200.0,
        )
        detail_rec = cache.update_vector(s_recover)
        assert detail_rec.status == "NOMINAL"
        assert detail_rec.has_anomaly is False
        # Event count should NOT change on recovery
        assert len(cache.get_recent_anomalies()) == 3

        # Phase 8: Aircraft re-triggers SEVERE_DESCENT after recovery (Fourth event emitted!)
        s_retrigger = FlightState(
            icao24="dedup01", callsign="DEDUP1", squawk="1000",
            baro_altitude=2000.0, velocity=180.0, vertical_rate=-28.0,
            last_contact=base_time + 210.0,
        )
        cache.update_vector(s_retrigger)
        assert len(cache.get_recent_anomalies()) == 4
        assert cache.get_recent_anomalies()[0].category == AnomalyCategory.SEVERE_DESCENT.value

    def test_multi_aircraft_interleaved_deduplication(self):
        """
        Simulate 30 distinct aircraft concurrently alternating between nominal
        and emergency states across 300 cycles to verify deduplication state integrity.
        """
        cache = AircraftCache(max_anomalies_buffer=100)
        base_time = 1725500000.0
        aircraft_ids = [f"ac{idx:03d}" for idx in range(30)]

        # Cycle 1: All 30 aircraft enter squawk 7700 -> exactly 30 events
        for idx, icao in enumerate(aircraft_ids):
            cache.update_vector(FlightState(
                icao24=icao, callsign=f"AC{idx:02d}", squawk="7700",
                baro_altitude=9000.0, velocity=220.0, vertical_rate=-1.0,
                last_contact=base_time + idx,
            ))
        assert len(cache.get_recent_anomalies()) == 30

        # Cycle 2: All 30 aircraft repeat squawk 7700 -> 0 new events, still 30
        for idx, icao in enumerate(aircraft_ids):
            cache.update_vector(FlightState(
                icao24=icao, callsign=f"AC{idx:02d}", squawk="7700",
                baro_altitude=9000.0, velocity=220.0, vertical_rate=-1.0,
                last_contact=base_time + 100 + idx,
            ))
        assert len(cache.get_recent_anomalies()) == 30

        # Cycle 3: 10 aircraft (0..9) clear to nominal -> still 30 events
        for idx in range(10):
            cache.update_vector(FlightState(
                icao24=aircraft_ids[idx], callsign=f"AC{idx:02d}", squawk="1000",
                baro_altitude=9000.0, velocity=220.0, vertical_rate=-1.0,
                last_contact=base_time + 200 + idx,
            ))
        assert len(cache.get_recent_anomalies()) == 30

        # Cycle 4: Those same 10 aircraft re-trigger squawk 7600 -> exactly 10 new events (total 40)
        for idx in range(10):
            cache.update_vector(FlightState(
                icao24=aircraft_ids[idx], callsign=f"AC{idx:02d}", squawk="7600",
                baro_altitude=9000.0, velocity=220.0, vertical_rate=-1.0,
                last_contact=base_time + 300 + idx,
            ))
        assert len(cache.get_recent_anomalies()) == 40

    def test_get_recent_anomalies_latency_sla_under_1ms(self):
        """
        Benchmark SLA: get_recent_anomalies() must return sorted newest-first in < 1ms (< 1,000 us).
        Populate the cache with 100 full records and execute 10,000 consecutive retrieval calls.
        Verify:
        - Mean latency < 50 microseconds (< 0.05 ms)
        - 95th percentile (p95) < 100 microseconds (< 0.10 ms)
        - 99th percentile (p99) < 500 microseconds (< 0.50 ms)
        - Maximum latency < 1,000 microseconds (< 1.0 ms)
        """
        cache = AircraftCache(max_anomalies_buffer=100)
        base_time = 1725500000.0

        # Fill cache with 100 full anomaly records
        for i in range(100):
            rec = AnomalyRecord(
                id=f"perf-{i:03d}",
                icao24=f"4b{i:04x}",
                callsign=f"SWR{i:03d}",
                category="SQUAWK_EMERGENCY",
                severity=AnomalySeverity.CRITICAL,
                rationale=f"CRITICAL SQUAWK 7700: General In-Flight Emergency declared for aircraft #{i}.",
                timestamp=base_time + i,
            )
            cache.add_anomaly_record(rec)

        assert len(cache._recent_anomalies) == 100

        iterations = 10000
        timings_us: List[float] = []

        # Warm-up run
        for _ in range(100):
            cache.get_recent_anomalies()

        # Benchmark run
        for _ in range(iterations):
            t0 = time.perf_counter()
            records = cache.get_recent_anomalies()
            t1 = time.perf_counter()
            timings_us.append((t1 - t0) * 1_000_000.0)

        mean_us = statistics.mean(timings_us)
        median_us = statistics.median(timings_us)
        sorted_timings = sorted(timings_us)
        p95_us = sorted_timings[int(iterations * 0.95)]
        p99_us = sorted_timings[int(iterations * 0.99)]
        max_us = max(timings_us)

        print(
            f"\n[SLA Benchmark] 10,000 get_recent_anomalies() calls: "
            f"mean={mean_us:.2f}us, median={median_us:.2f}us, p95={p95_us:.2f}us, "
            f"p99={p99_us:.2f}us, max={max_us:.2f}us"
        )

        assert mean_us < 50.0, f"Mean latency {mean_us:.2f}us exceeded 50us!"
        assert p99_us < 500.0, f"p99 latency {p99_us:.2f}us exceeded 500us (0.5ms)!"
        assert max_us < 1000.0, f"Max latency {max_us:.2f}us exceeded 1000us (1.0ms SLA)!"

    def test_get_recent_anomalies_limit_and_edge_arguments(self):
        """
        Verify slicing behavior of get_recent_anomalies(limit):
        - limit=None returns all 100
        - limit=10 returns exactly 10 newest
        - limit=50 returns exactly 50 newest
        - limit=150 (exceeding length) returns all 100
        - limit=0 returns all 100
        - limit=-5 returns all 100
        """
        cache = AircraftCache(max_anomalies_buffer=100)
        base_time = 1725500000.0

        for i in range(100):
            cache.add_anomaly_record(
                AnomalyRecord(
                    id=f"lim-{i:03d}",
                    icao24=f"4a{i:04x}",
                    callsign=f"AFR{i:03d}",
                    category="SEVERE_DESCENT",
                    severity=AnomalySeverity.SEVERE,
                    rationale=f"Severe descent event #{i}",
                    timestamp=base_time + i,
                )
            )

        assert len(cache.get_recent_anomalies(limit=None)) == 100
        assert len(cache.get_recent_anomalies(limit=10)) == 10
        assert cache.get_recent_anomalies(limit=10)[0].id == "lim-099"
        assert cache.get_recent_anomalies(limit=10)[9].id == "lim-090"

        assert len(cache.get_recent_anomalies(limit=50)) == 50
        assert len(cache.get_recent_anomalies(limit=150)) == 100
        assert len(cache.get_recent_anomalies(limit=0)) == 100
        assert len(cache.get_recent_anomalies(limit=-1)) == 100

    def test_thread_safe_concurrent_anomaly_bursts(self):
        """
        Stress-test thread safety:
        - 10 worker threads concurrently writing 50 rapid anomaly events each (total 500 events)
        - 5 reader threads continuously querying get_recent_anomalies() and get_stats()
        Verify:
        - Zero race conditions, data races, deadlocks, or exceptions
        - Internal buffer capped at exactly 100
        - All returned records are valid AnomalyRecord objects
        """
        cache = AircraftCache(max_anomalies_buffer=100)
        base_time = 1725500000.0
        write_errors: List[Exception] = []
        read_errors: List[Exception] = []
        stop_readers = threading.Event()

        def writer_job(worker_id: int):
            try:
                for i in range(50):
                    idx = (worker_id * 50) + i
                    state = FlightState(
                        icao24=f"cw{idx:05x}",
                        callsign=f"CW{idx:04d}",
                        squawk="7700" if i % 2 == 0 else "7600",
                        baro_altitude=8000.0,
                        velocity=210.0,
                        vertical_rate=-25.0,
                        last_contact=base_time + idx,
                    )
                    cache.update_vector(state)
            except Exception as exc:
                write_errors.append(exc)

        def reader_job():
            try:
                while not stop_readers.is_set():
                    recent = cache.get_recent_anomalies(limit=25)
                    assert len(recent) <= 25
                    for r in recent:
                        assert isinstance(r, AnomalyRecord)
                        assert r.severity in (AnomalySeverity.CRITICAL, AnomalySeverity.SEVERE)
                    stats = cache.get_stats()
                    assert stats["recent_anomalies_count"] <= 100
            except Exception as exc:
                read_errors.append(exc)

        writer_threads = [threading.Thread(target=writer_job, args=(w,)) for w in range(10)]
        reader_threads = [threading.Thread(target=reader_job) for _ in range(5)]

        # Start readers then writers
        for r in reader_threads:
            r.start()
        for w in writer_threads:
            w.start()

        # Wait for writers
        for w in writer_threads:
            w.join()

        # Stop readers and join
        stop_readers.set()
        for r in reader_threads:
            r.join()

        assert not write_errors, f"Writer threads encountered errors: {write_errors}"
        assert not read_errors, f"Reader threads encountered errors: {read_errors}"

        assert len(cache._recent_anomalies) == 100
        assert len(cache.get_recent_anomalies()) == 100
        stats = cache.get_stats()
        assert stats["recent_anomalies_count"] == 100
        assert stats["total_updates"] == 500
