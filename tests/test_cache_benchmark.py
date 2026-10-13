"""
tests/test_cache_benchmark.py - High-throughput performance benchmark for AircraftCache.

Validates that retrieving 1,500 active aircraft with 30-point ring buffers
completes under the 50ms SLA (typically < 1ms, surpassing SLA by > 50x).
"""

import statistics
import time
import pytest
from core.cache import AircraftCache
from models.aircraft import FlightState


@pytest.fixture(scope="module")
def populated_cache():
    """Populate cache with 1,500 flights having 30 history points each (45,000 vectors)."""
    cache = AircraftCache(max_trail_len=30)
    base_time = 1725550000.0

    for f_idx in range(1500):
        icao = f"{f_idx:06x}"
        for h_idx in range(30):
            state = FlightState(
                icao24=icao,
                callsign=f"AIR{f_idx % 999:03d}",
                origin_country="European Union",
                longitude=10.0 + (f_idx % 100) * 0.1,
                latitude=45.0 + (f_idx % 50) * 0.1,
                baro_altitude=10000.0 + h_idx * 10.0,
                velocity=230.0 + h_idx * 0.5,
                vertical_rate=0.0,
                squawk="1000",
                true_track=180.0,
                last_contact=base_time + h_idx * 10.0,
            )
            cache.update_vector(state)

    return cache


def test_cache_retrieval_under_50ms_sla(populated_cache):
    """Benchmark full active flight snapshot retrieval under 1,500 flights (45,000 trail points)."""
    cache = populated_cache
    assert len(cache._flights) == 1500
    iterations = 100
    latencies_ms = []

    # Warmup phase (5 iterations)
    for _ in range(5):
        _ = cache.get_all_active()

    # Benchmark phase (100 iterations)
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        active_flights = cache.get_all_active()
        t1 = time.perf_counter_ns()

        assert len(active_flights) == 1500
        latencies_ms.append((t1 - t0) / 1_000_000.0)

    # Compute statistical percentiles
    mean_lat = statistics.mean(latencies_ms)
    p50_lat = statistics.median(latencies_ms)
    sorted_lats = sorted(latencies_ms)
    p95_lat = sorted_lats[int(len(sorted_lats) * 0.95)]
    p99_lat = sorted_lats[int(len(sorted_lats) * 0.99)]
    max_lat = max(latencies_ms)

    print(f"\n--- AIRCRAFT CACHE BENCHMARK REPORT (1,500 FLIGHTS / 45,000 VECTORS) ---")
    print(f"Iterations:     {iterations}")
    print(f"Mean Latency:   {mean_lat:.4f} ms")
    print(f"P50 (Median):   {p50_lat:.4f} ms")
    print(f"P95:            {p95_lat:.4f} ms")
    print(f"P99:            {p99_lat:.4f} ms")
    print(f"Max Latency:    {max_lat:.4f} ms")
    print(f"SLA Target:     < 50.00 ms")
    print(f"Status:         {'PASSED' if p95_lat < 50.0 else 'FAILED'}")

    # Strict SLA Assertions
    assert p95_lat < 50.0, f"P95 cache retrieval latency ({p95_lat:.2f}ms) exceeded 50ms SLA!"
    assert max_lat < 50.0, f"Max cache retrieval latency ({max_lat:.2f}ms) exceeded 50ms SLA!"


def test_single_flight_lookup_under_1ms(populated_cache):
    """Benchmark random O(1) single aircraft detail lookup."""
    cache = populated_cache
    test_icaos = [f"{i:06x}" for i in range(0, 1500, 15)]  # 100 sample flights
    latencies_us = []

    for icao in test_icaos:
        t0 = time.perf_counter_ns()
        detail = cache.get_flight(icao)
        t1 = time.perf_counter_ns()
        elapsed_us = (t1 - t0) / 1_000.0
        latencies_us.append(elapsed_us)
        assert detail is not None
        assert len(detail.trail) == 30

    max_us = max(latencies_us)
    print(f"Single Flight Lookup Max: {max_us:.2f} µs (< 1000 µs SLA)")
    assert max_us < 1000.0, f"Single flight lookup took {max_us}µs, exceeding 1ms SLA!"
