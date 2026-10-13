"""
tests/test_cache.py - Unit tests for AircraftCache ring buffer, TTL, and concurrency.
"""

import asyncio
import time
import pytest
from core.cache import AircraftCache
from models.aircraft import FlightState


def make_flight(
    icao24: str,
    alt: float = 10000.0,
    speed: float = 230.0,
    lat: float = 48.0,
    lon: float = 10.0,
    squawk: str = "1000",
    ts: float = 1725550000.0,
    vert_rate: float = 0.0,
    on_ground: bool = False,
) -> FlightState:
    """Helper factory for valid FlightState instances."""
    return FlightState(
        icao24=icao24,
        callsign=f"TST{icao24[-3:].upper()}",
        origin_country="Testland",
        longitude=lon,
        latitude=lat,
        baro_altitude=alt,
        velocity=speed,
        vertical_rate=vert_rate,
        squawk=squawk,
        true_track=90.0,
        on_ground=on_ground,
        last_contact=ts,
    )


class TestRingBufferSlidingWindow:
    """Verify FIFO behavior of deque(maxlen=30)."""

    def test_ring_buffer_fifo_growth_and_eviction(self):
        cache = AircraftCache(max_trail_len=30)
        icao = "4b1812"

        # Insert 10 vectors
        for i in range(10):
            cache.update_vector(make_flight(icao, alt=10000.0 + i * 10, ts=1000.0 + i))

        detail = cache.get_flight(icao)
        assert detail is not None
        assert len(detail.history) == 10
        assert detail.history[0].timestamp == 1000.0
        assert detail.history[-1].timestamp == 1009.0

        # Insert 25 more vectors (total 35 updates)
        for i in range(10, 35):
            cache.update_vector(make_flight(icao, alt=10000.0 + i * 10, ts=1000.0 + i))

        detail = cache.get_flight(icao)
        assert detail is not None
        assert len(detail.history) == 30  # Capped at exactly 30!
        # Oldest 5 dropped: first item should be timestamp 1005.0 (35 - 30)
        assert detail.history[0].timestamp == 1005.0
        assert detail.history[-1].timestamp == 1034.0

    def test_trail_coordinates_extraction(self):
        cache = AircraftCache(max_trail_len=30)
        icao = "40061d"
        for i in range(5):
            cache.update_vector(make_flight(icao, lat=50.0 + i * 0.1, lon=2.0 + i * 0.1, ts=1000.0 + i))

        detail = cache.get_flight(icao)
        assert detail is not None
        assert len(detail.trail_coords) == 5
        assert detail.trail_coords[0] == [50.0, 2.0]
        assert detail.trail_coords[-1] == [pytest.approx(50.4), pytest.approx(2.4)]

    def test_sparkline_trend_generation(self):
        cache = AircraftCache(max_trail_len=30)
        icao = "3c6445"
        for i in range(20):
            cache.update_vector(make_flight(icao, alt=5000.0 + i * 100, speed=200.0 + i * 2, ts=1000.0 + i))

        detail = cache.get_flight(icao)
        assert detail is not None
        assert len(detail.sparklines["altitude"]) == 20
        assert len(detail.sparklines["speed"]) == 20
        assert detail.sparklines["altitude"][-1] == pytest.approx((5000.0 + 19 * 100) * 3.28084, rel=1e-2)


class TestTTLStaleFlightPruning:
    """Verify stale aircraft eviction."""

    def test_prune_stale_evicts_expired_retains_active(self):
        cache = AircraftCache()
        now = 2000.0

        # Flight A: last contact 150s ago (> 120s TTL) -> should be evicted
        cache.update_vector(make_flight("stale01", ts=now - 150.0))
        # Flight B: last contact 80s ago (<= 120s TTL) -> should be retained
        cache.update_vector(make_flight("fresh01", ts=now - 80.0))
        # Flight C: last contact 10s ago -> retained
        cache.update_vector(make_flight("fresh02", ts=now - 10.0))

        assert len(cache.get_all_active()) == 3
        pruned_count = cache.prune_stale(now=now, ttl_seconds=120.0)

        assert pruned_count == 1
        assert cache.get_flight("stale01") is None
        assert cache.get_flight("fresh01") is not None
        assert cache.get_flight("fresh02") is not None
        assert len(cache.get_all_active()) == 2

    def test_prune_empty_cache_returns_zero(self):
        cache = AircraftCache()
        assert cache.prune_stale(now=2000.0) == 0


class TestConcurrencyResilience:
    """Verify thread and async safety under simultaneous read/write workload."""

    @pytest.mark.asyncio
    async def test_concurrent_reads_and_writes_no_exceptions(self):
        cache = AircraftCache()
        stop_flag = False

        async def writer():
            while not stop_flag:
                for i in range(50):
                    icao = f"flt{i:03d}"
                    cache.update_vector(make_flight(icao, ts=time.time()))
                await asyncio.sleep(0.001)

        async def reader():
            while not stop_flag:
                # Must never raise RuntimeError: dictionary changed size during iteration
                active = cache.get_all_active()
                assert isinstance(active, list)
                stats = cache.get_stats()
                assert "active_count" in stats
                await asyncio.sleep(0.001)

        async def pruner():
            while not stop_flag:
                cache.prune_stale(now=time.time(), ttl_seconds=120.0)
                await asyncio.sleep(0.005)

        # Launch concurrent tasks
        tasks = [
            asyncio.create_task(writer()),
            asyncio.create_task(reader()),
            asyncio.create_task(reader()),
            asyncio.create_task(pruner())
        ]

        # Run for 0.25 seconds under heavy concurrency
        await asyncio.sleep(0.25)
        stop_flag = True
        await asyncio.gather(*tasks)

        assert len(cache.get_all_active()) == 50

    def test_airborne_filter_and_stats(self):
        cache = AircraftCache()
        cache.update_vector(make_flight("air01", on_ground=False))
        cache.update_vector(make_flight("gnd01", on_ground=True))

        assert len(cache.get_all_active(airborne_only=False)) == 2
        assert len(cache.get_all_active(airborne_only=True)) == 1

        stats = cache.get_stats()
        assert stats["total_tracked"] == 2
        assert stats["active_airborne"] == 1
        assert stats["active_on_ground"] == 1
