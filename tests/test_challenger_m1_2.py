"""
tests/test_challenger_m1_2.py
Milestone 1 Challenger 2 Empirical Stress Test Suite.

Scope & Mission:
1. Synthetic Replay Long-Run Continuity & Bounding Box Stress Test:
   - 1,000 continuous simulation steps.
   - Trajectory continuity (no teleportation or NaN coordinates).
   - Coordinates strictly within European bounds (20 <= lat <= 60, -10 <= lon <= 40).
   - Nominal flights produce 0 false positives across all 1,000 steps.
   - Scripted anomalies maintain exact expected trigger conditions.
   - Multi-seed stability across extended steps.
   - Cache saturation and ring-buffer boundary invariants over 1,000 steps.

2. Ingestion Network Fault Injection:
   - Repeated HTTP 429 rate limit bursts.
   - Connection & read timeouts (httpx.TimeoutException).
   - DNS name resolution failure (httpx.ConnectError / gaierror).
   - Mixed chaos sequence with seamless fallback and full live recovery.
   - Exponential backoff scaling and full jitter distribution verification.
   - Background worker task lifecycle (start, run, stop) under continuous faults.
"""

import asyncio
import math
import socket
import time
from typing import Any, Dict, List, Optional
import pytest
import httpx

from core.cache import AircraftCache
from core.ingestion import (
    OpenSkyIngestionWorker,
    IngestionMode,
    BACKOFF_BASE_SECONDS,
    BACKOFF_MAX_SECONDS,
    BACKOFF_JITTER_MIN,
    BACKOFF_JITTER_MAX,
)
from core.synthetic import SyntheticReplayGenerator, SyntheticFlightTemplate


# ============================================================================
# PART 1: SYNTHETIC REPLAY LONG-RUN CONTINUITY & BOUNDING BOX STRESS TESTS
# ============================================================================

class TestSyntheticReplayLongRunStress:
    """Empirically stress-test SyntheticReplayGenerator over long horizons."""

    def test_1000_steps_continuity_and_bounding_box(self):
        """
        Execute SyntheticReplayGenerator across 1,000 continuous simulation steps.
        Verify:
        - Exactly 40 aircraft per step (total 40,000 observations).
        - No NaN or Inf or None coordinates.
        - Strict confinement to European bounds: 20 <= lat <= 60, -10 <= lon <= 40.
        - Step-to-step trajectory continuity: maximum displacement per 10s step <= 4.0 km
          (ruling out teleportation).
        """
        gen = SyntheticReplayGenerator(seed=42)
        total_steps = 1000
        dt = 10.0

        min_lat, max_lat = 999.0, -999.0
        min_lon, max_lon = 999.0, -999.0
        max_step_dist_km = 0.0

        prev_positions = {f.template.icao24: (f.lat, f.lon) for f in gen.flights}

        for step in range(1, total_steps + 1):
            states = gen.tick(dt=dt)
            assert len(states) == 40, f"Step {step}: expected 40 flights, got {len(states)}"

            for s in states:
                # 1. No None or NaN or Inf coordinates
                assert s.latitude is not None, f"Step {step} flight {s.icao24}: latitude is None"
                assert s.longitude is not None, f"Step {step} flight {s.icao24}: longitude is None"
                assert not math.isnan(s.latitude), f"Step {step} flight {s.icao24}: latitude is NaN"
                assert not math.isnan(s.longitude), f"Step {step} flight {s.icao24}: longitude is NaN"
                assert not math.isinf(s.latitude), f"Step {step} flight {s.icao24}: latitude is Inf"
                assert not math.isinf(s.longitude), f"Step {step} flight {s.icao24}: longitude is Inf"

                # 2. Strict European Bounding Box: 20 <= lat <= 60, -10 <= lon <= 40
                assert 20.0 <= s.latitude <= 60.0, (
                    f"Step {step} flight {s.icao24}: lat {s.latitude} outside [20.0, 60.0]"
                )
                assert -10.0 <= s.longitude <= 40.0, (
                    f"Step {step} flight {s.icao24}: lon {s.longitude} outside [-10.0, 40.0]"
                )

                min_lat = min(min_lat, s.latitude)
                max_lat = max(max_lat, s.latitude)
                min_lon = min(min_lon, s.longitude)
                max_lon = max(max_lon, s.longitude)

                # 3. Trajectory continuity (no teleportation)
                prev_lat, prev_lon = prev_positions[s.icao24]
                dlat_km = (s.latitude - prev_lat) * 111.32
                dlon_km = (s.longitude - prev_lon) * 111.32 * math.cos(math.radians(s.latitude))
                step_dist_km = math.hypot(dlat_km, dlon_km)

                # At max velocity 355 m/s, 10s displacement is ~3.55 km. Allowing up to 4.0 km for curvature.
                assert step_dist_km <= 4.0, (
                    f"Step {step} flight {s.icao24}: teleportation detected! Jumped {step_dist_km:.3f} km"
                )
                if step_dist_km > max_step_dist_km:
                    max_step_dist_km = step_dist_km

                prev_positions[s.icao24] = (s.latitude, s.longitude)

        # Confirm observed bounds are realistic within Europe
        assert 21.0 <= min_lat < 25.0
        assert 57.0 < max_lat <= 60.0
        assert -10.0 <= min_lon < -8.0
        assert 35.0 < max_lon <= 40.0
        assert 3.0 < max_step_dist_km <= 3.8

    def test_nominal_flights_zero_false_positives_1000_steps(self):
        """
        Verify that all 35 nominal commercial flights produce exactly 0 false positives
        across all 1,000 continuous simulation steps (35,000 nominal observations).
        """
        gen = SyntheticReplayGenerator(seed=42)
        nominal_icaos = {f.template.icao24 for f in gen.flights if not f.template.is_anomaly}
        assert len(nominal_icaos) == 35

        false_positive_squawk = 0
        false_positive_descent = 0
        false_positive_overspeed = 0

        for step in range(1, 1001):
            states = gen.tick(dt=10.0)
            for s in states:
                if s.icao24 in nominal_icaos:
                    # Check Squawk Trap: 7500, 7600, 7700
                    if s.squawk in {"7500", "7600", "7700"}:
                        false_positive_squawk += 1

                    # Check Severe Descent Trap: vertical_rate < -20.32 m/s
                    if s.vertical_rate is not None and s.vertical_rate < -20.32:
                        false_positive_descent += 1

                    # Check Overspeed Outlier Trap: velocity > 330.0 m/s below 10,000m
                    if s.velocity is not None and s.velocity > 330.0:
                        if s.baro_altitude is not None and s.baro_altitude < 10000.0:
                            false_positive_overspeed += 1

        assert false_positive_squawk == 0, f"False positive squawks detected: {false_positive_squawk}"
        assert false_positive_descent == 0, f"False positive descents detected: {false_positive_descent}"
        assert false_positive_overspeed == 0, f"False positive overspeeds detected: {false_positive_overspeed}"

    def test_scripted_anomalies_maintain_exact_expected_triggers(self):
        """
        Verify that all 5 scripted anomalies maintain their exact trigger conditions
        across all 1,000 steps (5,000 anomaly observations).
        """
        gen = SyntheticReplayGenerator(seed=42)

        for step in range(1, 1001):
            states = gen.tick(dt=10.0)
            state_map = {s.icao24: s for s in states}

            # 1. HIJACK1 (a07500): Squawk 7500
            s_hijack = state_map["a07500"]
            assert s_hijack.squawk == "7500", f"Step {step}: HIJACK1 squawk is {s_hijack.squawk}"

            # 2. NORDO2 (a07600): Squawk 7600
            s_nordo = state_map["a07600"]
            assert s_nordo.squawk == "7600", f"Step {step}: NORDO2 squawk is {s_nordo.squawk}"

            # 3. EMRG77 (a07700): Squawk 7700
            s_emrg = state_map["a07700"]
            assert s_emrg.squawk == "7700", f"Step {step}: EMRG77 squawk is {s_emrg.squawk}"

            # 4. DIVE99 (a00001): Severe Descent (< -20.32 m/s, strictly -25.5 m/s)
            s_dive = state_map["a00001"]
            assert s_dive.vertical_rate is not None and s_dive.vertical_rate < -20.32, (
                f"Step {step}: DIVE99 vertical rate is {s_dive.vertical_rate}"
            )
            assert s_dive.vertical_rate == -25.50
            # Ensure altitude recyclers keep altitude within safe positive bounds
            assert s_dive.baro_altitude is not None and s_dive.baro_altitude >= 2400.0

            # 5. MACH01 (a00002): Overspeed (> 330 m/s at alt < 10000m)
            s_mach = state_map["a00002"]
            assert s_mach.velocity is not None and s_mach.velocity > 330.0, (
                f"Step {step}: MACH01 velocity is {s_mach.velocity}"
            )
            assert s_mach.velocity == 355.0
            assert s_mach.baro_altitude is not None and s_mach.baro_altitude < 10000.0, (
                f"Step {step}: MACH01 altitude is {s_mach.baro_altitude}"
            )
            assert s_mach.baro_altitude == 6200.0

    @pytest.mark.parametrize("seed", [1, 99, 404, 7777, 88888])
    def test_multi_seed_bounding_box_stability(self, seed: int):
        """Verify bounding box confinement across varying random seeds (250 steps each)."""
        gen = SyntheticReplayGenerator(seed=seed)
        for _ in range(250):
            states = gen.tick(dt=10.0)
            for s in states:
                assert 20.0 <= s.latitude <= 60.0
                assert -10.0 <= s.longitude <= 40.0
                assert not math.isnan(s.latitude)
                assert not math.isnan(s.longitude)

    def test_cache_saturation_over_1000_steps(self):
        """
        Ingest 1,000 steps (40,000 state updates) into AircraftCache.
        Verify:
        - Cache retains exactly 40 active aircraft.
        - Each aircraft's ring buffer stays capped at exactly 30 TrailPoints.
        - Sparkline arrays stay capped at 30 points.
        - Snapshot retrieval latency remains sub-millisecond (< 5ms).
        """
        cache = AircraftCache(max_trail_len=30)
        gen = SyntheticReplayGenerator(seed=42)

        for _ in range(1000):
            states = gen.tick(dt=10.0)
            for s in states:
                cache.update_vector(s)

        active = cache.get_all_active()
        assert len(active) == 40

        for ac in active:
            assert len(ac.trail) == 30, f"Aircraft {ac.icao24} trail len is {len(ac.trail)}, expected 30"
            assert len(ac.altitude_sparkline) == 30
            assert len(ac.speed_sparkline) == 30

        # Measure snapshot latency
        t0 = time.perf_counter()
        for _ in range(50):
            _ = cache.get_all_active()
        mean_ms = ((time.perf_counter() - t0) / 50.0) * 1000.0

        assert mean_ms < 5.0, f"Snapshot latency degraded to {mean_ms:.3f} ms after 1,000 steps"


# ============================================================================
# PART 2: INGESTION NETWORK FAULT INJECTION TESTS
# ============================================================================

class TestIngestionNetworkFaultInjection:
    """Fault injection suite testing HTTP 429, timeouts, DNS failures, backoff, and recovery."""

    @pytest.mark.asyncio
    async def test_repeated_http_429_bursts_and_fallback(self):
        """
        Inject 10 consecutive HTTP 429 responses.
        Verify:
        - Worker increments http_429_count and consecutive_errors to 10.
        - Worker stays in IngestionMode.SYNTHETIC_FALLBACK.
        - Cache continues to be populated with 40 fresh synthetic aircraft per cycle.
        - Cache data remains accessible without interruption.
        """
        cache = AircraftCache()
        gen = SyntheticReplayGenerator(seed=42)

        class RateLimitTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                return httpx.Response(429, headers={"Retry-After": "30"}, request=request)

        client = httpx.AsyncClient(transport=RateLimitTransport())
        worker = OpenSkyIngestionWorker(cache=cache, synthetic_generator=gen, client=client)

        for cycle in range(1, 11):
            result = await worker.poll_once()
            assert result.success is False
            assert result.mode == IngestionMode.SYNTHETIC_FALLBACK
            assert result.status_code == 429
            assert worker.diagnostics.http_429_count == cycle
            assert worker.diagnostics.consecutive_errors == cycle

            # Cache continues serving 40 flights seamlessly
            active = cache.get_all_active()
            assert len(active) == 40
            assert all(f.latitude is not None and f.longitude is not None for f in active)

        await client.aclose()

    @pytest.mark.asyncio
    async def test_connection_and_read_timeouts_fallback(self):
        """
        Inject connection and read timeouts.
        Verify:
        - Worker increments timeout_count.
        - Worker switches to SYNTHETIC_FALLBACK mode.
        - Cache continues serving valid data without interruption.
        """
        cache = AircraftCache()
        gen = SyntheticReplayGenerator(seed=42)

        class TimeoutTransport(httpx.AsyncBaseTransport):
            def __init__(self):
                self.calls = 0
            async def handle_async_request(self, request):
                self.calls += 1
                if self.calls % 2 == 1:
                    raise httpx.ConnectTimeout("Connection to opensky-network.org timed out", request=request)
                else:
                    raise httpx.ReadTimeout("Read socket timed out", request=request)

        client = httpx.AsyncClient(transport=TimeoutTransport())
        worker = OpenSkyIngestionWorker(cache=cache, synthetic_generator=gen, client=client)

        for cycle in range(1, 7):
            result = await worker.poll_once()
            assert result.success is False
            assert result.mode == IngestionMode.SYNTHETIC_FALLBACK
            assert worker.diagnostics.timeout_count == cycle
            assert worker.diagnostics.consecutive_errors == cycle

            # Cache check
            active = cache.get_all_active()
            assert len(active) == 40

        await client.aclose()

    @pytest.mark.asyncio
    async def test_dns_name_resolution_failure_fallback(self):
        """
        Inject DNS resolution failure (socket.gaierror wrapped in httpx.ConnectError).
        Verify:
        - Worker catches DNS exception cleanly without crashing.
        - Increments consecutive_errors and failed_polls.
        - Switches to SYNTHETIC_FALLBACK.
        - Cache serves valid data without interruption.
        """
        cache = AircraftCache()
        gen = SyntheticReplayGenerator(seed=42)

        class DnsFailureTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                gai = socket.gaierror(-3, "Temporary failure in name resolution")
                raise httpx.ConnectError(f"[Errno -3] {gai}", request=request)

        client = httpx.AsyncClient(transport=DnsFailureTransport())
        worker = OpenSkyIngestionWorker(cache=cache, synthetic_generator=gen, client=client)

        for cycle in range(1, 6):
            result = await worker.poll_once()
            assert result.success is False
            assert result.mode == IngestionMode.SYNTHETIC_FALLBACK
            assert worker.diagnostics.consecutive_errors == cycle
            assert worker.diagnostics.failed_polls == cycle
            assert "Connection failure communicating with OpenSky" in result.error_message

            # Cache check
            active = cache.get_all_active()
            assert len(active) == 40

        await client.aclose()

    @pytest.mark.asyncio
    async def test_mixed_network_chaos_and_live_recovery(self):
        """
        Inject an interleaved chaos scenario:
        200 OK -> 429 -> Timeout -> DNS -> 429 -> 429 -> 200 OK -> Timeout -> DNS -> 200 OK.
        Verify seamless transitions between LIVE_OPENSKY and SYNTHETIC_FALLBACK,
        proper counter increments, error reset on recovery, and continuous cache availability.
        """
        cache = AircraftCache()
        gen = SyntheticReplayGenerator(seed=42)

        chaos_script = [
            "200",      # 1
            "429",      # 2
            "timeout",  # 3
            "dns",      # 4
            "429",      # 5
            "429",      # 6
            "200",      # 7 (recovery)
            "timeout",  # 8
            "dns",      # 9
            "200",      # 10 (recovery)
        ]

        class ChaosTransport(httpx.AsyncBaseTransport):
            def __init__(self):
                self.idx = 0

            async def handle_async_request(self, request):
                action = chaos_script[self.idx]
                self.idx += 1
                if action == "200":
                    return httpx.Response(
                        200,
                        json={"time": int(time.time()), "states": gen.generate_raw_states()},
                        request=request
                    )
                elif action == "429":
                    return httpx.Response(429, request=request)
                elif action == "timeout":
                    raise httpx.ReadTimeout("Read timed out", request=request)
                elif action == "dns":
                    raise httpx.ConnectError("DNS failure", request=request)
                raise ValueError(f"Unknown chaos action: {action}")

        client = httpx.AsyncClient(transport=ChaosTransport())
        worker = OpenSkyIngestionWorker(cache=cache, synthetic_generator=gen, client=client)

        for step_num, expected_action in enumerate(chaos_script, start=1):
            result = await worker.poll_once()

            if expected_action == "200":
                assert result.success is True
                assert result.mode == IngestionMode.LIVE_OPENSKY
                assert worker.diagnostics.consecutive_errors == 0
                assert worker.diagnostics.current_backoff_seconds == 0.0
            else:
                assert result.success is False
                assert result.mode == IngestionMode.SYNTHETIC_FALLBACK
                assert worker.diagnostics.consecutive_errors > 0

            # Cache invariant: ALWAYS serves 40 flights with valid coordinates
            active = cache.get_all_active()
            assert len(active) == 40
            assert all(f.latitude is not None and f.longitude is not None for f in active)

        await client.aclose()

    def test_exponential_backoff_and_full_jitter_distribution(self):
        """
        Verify mathematical properties of _calculate_backoff():
        - Exponent caps at min(consecutive_errors, 6).
        - Value strictly bounded in [BACKOFF_BASE_SECONDS + JITTER_MIN, BACKOFF_MAX_SECONDS + JITTER_MAX].
        - Jitter creates significant variance across repeated calls (not deterministic).
        """
        cache = AircraftCache()
        worker = OpenSkyIngestionWorker(cache=cache)

        # Baseline: 1 error
        worker.diagnostics.consecutive_errors = 1
        samples_1 = [worker._calculate_backoff() for _ in range(100)]
        assert all(10.5 <= s <= 22.0 for s in samples_1)
        assert len(set(samples_1)) > 80  # Demonstrates jitter randomness

        # 3 errors (temp = 80 -> capped at 60)
        worker.diagnostics.consecutive_errors = 3
        samples_3 = [worker._calculate_backoff() for _ in range(100)]
        assert all(10.5 <= s <= 62.0 for s in samples_3)
        assert len(set(samples_3)) > 80

        # Saturated: 10 errors (capped at 6)
        worker.diagnostics.consecutive_errors = 10
        samples_10 = [worker._calculate_backoff() for _ in range(100)]
        assert all(10.5 <= s <= 62.0 for s in samples_10)
        assert max(samples_10) > 55.0  # Upper boundary reachable
        assert min(samples_10) >= 10.5 # Lower boundary respected

    @pytest.mark.asyncio
    async def test_worker_background_loop_lifecycle_under_faults(self):
        """
        Verify start(), background execution during continuous 429s, and graceful stop().
        Ensures task cancellation does not leave dangling tasks or leaked resources.
        """
        cache = AircraftCache()
        gen = SyntheticReplayGenerator(seed=42)

        class Continuous429Transport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                return httpx.Response(429, request=request)

        client = httpx.AsyncClient(transport=Continuous429Transport())
        worker = OpenSkyIngestionWorker(
            cache=cache,
            synthetic_generator=gen,
            poll_interval=0.05,  # fast poll for testing
            client=client,
        )

        task = worker.start()
        assert not task.done()
        # Yield to event loop to allow task to start
        await asyncio.sleep(0.05)
        assert worker._is_running is True

        # Let loop run for a few cycles
        await asyncio.sleep(0.25)

        assert worker.diagnostics.http_429_count >= 1
        assert worker.diagnostics.mode == IngestionMode.SYNTHETIC_FALLBACK

        # Graceful stop
        await worker.stop()
        assert worker._is_running is False
        assert task.done()
        assert worker.diagnostics.mode == IngestionMode.STOPPED

        await client.aclose()
