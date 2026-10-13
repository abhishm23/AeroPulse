"""
tests/test_concurrency_stress.py - Empirical Concurrency Stress Test Harness for AircraftCache.
Verifies thread safety, deadlock freedom, data integrity, and FIFO ring buffer invariants
under high-contention multi-threaded workloads (20+ concurrent OS threads, tens of thousands of ops).
"""

import math
import random
import threading
import time
from typing import List, Dict, Any
import pytest

from core.cache import AircraftCache
from models.aircraft import FlightState, AircraftDetail, TrailPoint


def generate_flight(
    icao24: str,
    callsign: str,
    seq: int,
    base_time: float,
    on_ground: bool = False,
) -> FlightState:
    """Deterministic factory for concurrent state vector generation."""
    lat = 40.0 + (seq % 100) * 0.1
    lon = -5.0 + (seq % 100) * 0.1
    alt = 1000.0 + (seq % 50) * 200.0
    vel = 150.0 + (seq % 30) * 5.0
    vert = -10.0 + (seq % 20) * 1.0
    return FlightState(
        icao24=icao24,
        callsign=callsign,
        origin_country="Country",
        longitude=lon,
        latitude=lat,
        baro_altitude=alt,
        velocity=vel,
        vertical_rate=vert,
        squawk="1000",
        true_track=float(seq % 360),
        on_ground=on_ground,
        last_contact=base_time + seq * 1.0,
    )


class TestAircraftCacheConcurrencyStress:
    """Empirical multi-threaded stress harness for AircraftCache."""

    def test_high_contention_concurrency_stress_partitioned_keys(self):
        """
        Runs 24 concurrent OS threads with monotonically sequenced updates:
        - 10 fast writer threads updating 5,000 vectors each (50,000 total updates)
        - 8 fast reader threads querying get_all_active, get_flight, and verifying invariants
        - 2 background pruner threads continuously evicting stale flights
        - 2 stats inspector threads asserting invariant consistency
        - 2 anomaly setter threads updating severity classifications
        """
        cache = AircraftCache(max_trail_len=30)
        num_writers = 10
        num_readers = 8
        num_pruners = 2
        num_stats = 2
        num_anom = 2
        total_threads = num_writers + num_readers + num_pruners + num_stats + num_anom
        assert total_threads >= 20, f"Expected 20+ threads, got {total_threads}"

        updates_per_writer = 5000
        expected_total_updates = num_writers * updates_per_writer  # 50,000 updates

        start_barrier = threading.Barrier(total_threads)
        stop_event = threading.Event()

        errors: List[Exception] = []
        errors_lock = threading.Lock()

        def record_error(err: Exception):
            with errors_lock:
                errors.append(err)

        # 1. Writer Threads (Each writer owns a distinct partition of flights, guaranteeing monotonic sequential feeds per flight)
        def writer_worker(thread_id: int):
            try:
                start_barrier.wait(timeout=10.0)
                base_time = 1000.0
                # Writer owns 10 flight IDs: f"{thread_id:02x}{idx:04x}"
                for i in range(updates_per_writer):
                    flight_idx = i % 10
                    icao = f"w{thread_id:01x}{flight_idx:04x}"
                    on_ground = (i % 7 == 0)
                    # seq advances monotonically per flight
                    seq = i // 10
                    fs = generate_flight(icao, f"C{icao.upper()}", seq, base_time, on_ground)
                    detail = cache.update_vector(fs)

                    # Immediate sanity check
                    assert detail.icao24 == icao.lower()
                    assert len(detail.trail) <= 30
            except Exception as e:
                record_error(e)

        # 2. Reader Threads
        reader_queries = [0] * num_readers

        def reader_worker(thread_id: int):
            try:
                start_barrier.wait(timeout=10.0)
                count = 0
                while not stop_event.is_set():
                    airborne_only = (count % 2 == 1)
                    active = cache.get_all_active(airborne_only=airborne_only)
                    assert isinstance(active, list)

                    for flight in active:
                        # Invariant 1: trail length must never exceed 30
                        trail_len = len(flight.trail)
                        assert trail_len <= 30, f"Trail length {trail_len} exceeded maxlen 30!"

                        # Invariant 2: FIFO order (timestamps monotonically non-decreasing)
                        if trail_len > 1:
                            for idx in range(1, trail_len):
                                t_prev = flight.trail[idx - 1].timestamp
                                t_curr = flight.trail[idx].timestamp
                                assert t_curr >= t_prev, f"FIFO order violation: {t_curr} < {t_prev}"

                        # Invariant 3: Coordinates matching
                        coords = flight.trail_coords
                        assert len(coords) == trail_len
                        if trail_len > 0:
                            assert coords[-1] == [flight.trail[-1].lat, flight.trail[-1].lon]

                    # Targeted single flight lookup
                    writer_id = count % num_writers
                    target_icao = f"w{writer_id:01x}0000"
                    target = cache.get_flight(target_icao)
                    if target is not None:
                        assert target.icao24 == target_icao

                    count += 1
                reader_queries[thread_id] = count
            except Exception as e:
                record_error(e)

        # 3. Pruner Threads
        prune_counts = [0] * num_pruners

        def pruner_worker(thread_id: int):
            try:
                start_barrier.wait(timeout=10.0)
                sim_time = 1000.0
                while not stop_event.is_set():
                    sim_time += 1.0
                    pruned = cache.prune_stale(ttl_seconds=120.0, now=sim_time)
                    prune_counts[thread_id] += pruned
                    time.sleep(0.001)
            except Exception as e:
                record_error(e)

        # 4. Stats Inspector Threads
        def stats_worker(thread_id: int):
            try:
                start_barrier.wait(timeout=10.0)
                while not stop_event.is_set():
                    stats = cache.get_stats()
                    assert "total_tracked" in stats
                    assert "active_airborne" in stats
                    assert "active_on_ground" in stats
                    assert stats["active_airborne"] + stats["active_on_ground"] == stats["total_tracked"], (
                        f"Stats mismatch: {stats['active_airborne']} + {stats['active_on_ground']} != {stats['total_tracked']}"
                    )
                    time.sleep(0.002)
            except Exception as e:
                record_error(e)

        # 5. Anomaly Setter Threads
        def anomaly_worker(thread_id: int):
            try:
                start_barrier.wait(timeout=10.0)
                count = 0
                severities = ["NOMINAL", "WARNING", "SEVERE", "CRITICAL"]
                while not stop_event.is_set():
                    writer_id = count % num_writers
                    target_icao = f"w{writer_id:01x}0000"
                    sev = severities[count % len(severities)]
                    cache.set_anomalies(target_icao, anomalies=[{"type": "TEST", "sev": sev}], status=sev)
                    count += 1
                    time.sleep(0.001)
            except Exception as e:
                record_error(e)

        # Launch all threads
        threads: List[threading.Thread] = []
        for i in range(num_writers):
            threads.append(threading.Thread(target=writer_worker, args=(i,), name=f"writer-{i}"))
        for i in range(num_readers):
            threads.append(threading.Thread(target=reader_worker, args=(i,), name=f"reader-{i}"))
        for i in range(num_pruners):
            threads.append(threading.Thread(target=pruner_worker, args=(i,), name=f"pruner-{i}"))
        for i in range(num_stats):
            threads.append(threading.Thread(target=stats_worker, args=(i,), name=f"stats-{i}"))
        for i in range(num_anom):
            threads.append(threading.Thread(target=anomaly_worker, args=(i,), name=f"anom-{i}"))

        t_start = time.perf_counter()
        for t in threads:
            t.start()

        # Wait for all writer threads to finish their 50,000 updates
        for t in threads[:num_writers]:
            t.join(timeout=30.0)
            assert not t.is_alive(), f"Writer thread {t.name} deadlocked or timed out!"

        # Stop reader, pruner, stats, and anomaly threads
        stop_event.set()

        for t in threads[num_writers:]:
            t.join(timeout=10.0)
            assert not t.is_alive(), f"Background thread {t.name} deadlocked or failed to terminate!"

        elapsed = time.perf_counter() - t_start
        total_reader_queries = sum(reader_queries)

        print(f"\n--- CONCURRENCY STRESS TEST (PARTITIONED) COMPLETED ---")
        print(f"Total Worker Threads: {total_threads}")
        print(f"Total Updates Performed: {expected_total_updates} across {num_writers} writers")
        print(f"Total Reader Queries: {total_reader_queries} across {num_readers} readers")
        print(f"Total Elapsed Time: {elapsed:.2f}s ({expected_total_updates / elapsed:.1f} writes/sec)")
        print(f"Total Errors Encountered: {len(errors)}")

        # Check for any exceptions caught during concurrent execution
        if errors:
            first_err = errors[0]
            raise AssertionError(f"Encountered {len(errors)} errors during concurrency stress! First: {first_err}")

        # Post-run Cache State Reconciliation
        final_stats = cache.get_stats()
        assert final_stats["total_updates"] == expected_total_updates, (
            f"Expected total_updates {expected_total_updates}, got {final_stats['total_updates']}"
        )
        assert final_stats["stale_pruned_total"] == sum(prune_counts), (
            f"Expected stale_pruned_total {sum(prune_counts)}, got {final_stats['stale_pruned_total']}"
        )

        # Invariant check on every remaining aircraft in cache
        all_remaining = cache.get_all_active()
        for flight in all_remaining:
            assert len(flight.trail) <= 30
            if len(flight.trail) > 1:
                for idx in range(1, len(flight.trail)):
                    assert flight.trail[idx].timestamp >= flight.trail[idx - 1].timestamp


    def test_unpartitioned_multiwriter_same_flight_stress(self):
        """
        Stress-tests multiple writer threads updating the exact SAME flights concurrently.
        Verifies RLock serialization: no deadlocks, no exceptions, no partial writes.
        """
        cache = AircraftCache(max_trail_len=30)
        num_writers = 10
        num_readers = 10
        total_threads = num_writers + num_readers
        updates_per_writer = 2000  # 20,000 total updates to only 5 shared flights!

        start_barrier = threading.Barrier(total_threads)
        stop_event = threading.Event()
        errors = []
        errors_lock = threading.Lock()

        def record_error(err):
            with errors_lock:
                errors.append(err)

        def writer_worker(thread_id: int):
            try:
                start_barrier.wait(timeout=10.0)
                for i in range(updates_per_writer):
                    icao = f"flt{i % 5:03d}"
                    # Use current time so timestamps generally increase
                    fs = FlightState(
                        icao24=icao,
                        callsign=f"C{icao.upper()}",
                        latitude=45.0 + (i % 20) * 0.1,
                        longitude=10.0 + (i % 20) * 0.1,
                        baro_altitude=5000.0 + i,
                        velocity=200.0,
                        last_contact=time.time(),
                    )
                    detail = cache.update_vector(fs)
                    assert detail.icao24 == icao
            except Exception as e:
                record_error(e)

        def reader_worker(thread_id: int):
            try:
                start_barrier.wait(timeout=10.0)
                while not stop_event.is_set():
                    active = cache.get_all_active()
                    assert len(active) <= 5
                    for f in active:
                        assert len(f.trail) <= 30
                        assert f.icao24 in {"flt000", "flt001", "flt002", "flt003", "flt004"}
                    stats = cache.get_stats()
                    assert stats["total_tracked"] <= 5
            except Exception as e:
                record_error(e)

        threads = []
        for i in range(num_writers):
            threads.append(threading.Thread(target=writer_worker, args=(i,)))
        for i in range(num_readers):
            threads.append(threading.Thread(target=reader_worker, args=(i,)))

        for t in threads:
            t.start()

        for t in threads[:num_writers]:
            t.join(timeout=20.0)
            assert not t.is_alive()

        stop_event.set()
        for t in threads[num_writers:]:
            t.join(timeout=10.0)
            assert not t.is_alive()

        if errors:
            raise AssertionError(f"Encountered errors: {errors[0]}")

        final_stats = cache.get_stats()
        assert final_stats["total_updates"] == num_writers * updates_per_writer
        assert final_stats["total_tracked"] == 5
