"""
tests/test_challenger_m3_1.py - Empirical Adversarial Challenge Suite for Milestone 3 (REST API Services).

Author: Challenger 1 (Milestone 3: Backend REST & WebSocket Services)
Scope & Mission:
1. Concurrency & High-Throughput Load Testing:
   - Empirical load tests issuing 250+ concurrent requests across all 5 REST endpoints:
     (/api/telemetry, /api/flight/{icao24}, /api/anomalies, /api/stats, /api/health).
   - Async load testing via httpx.AsyncClient with ASGITransport.
   - Multi-threaded load testing via ThreadPoolExecutor with TestClient.
2. Robustness & SLA Verification:
   - Verify 0 unhandled exceptions / 0 HTTP 500 responses under all conditions.
   - Verify p95 response time is strictly < 50.0 ms across all endpoints under concurrent load.
   - Verify p95 response time under high-contention concurrent read/write workloads (< 50.0 ms).
   - Verify p95 response time under large cache scale (1,500 active flights / 45,000 trail points).
3. 404 Status Code & Route Robustness:
   - Verify correct HTTP 404 status code and descriptive detail envelope when querying non-existent ICAO24s.
   - Verify case-insensitivity and whitespace stripping on flight lookups.
   - Verify resilience against adversarial/malformed ICAO inputs (special characters, symbols, traversal attempts).
4. Response Schema Validity & Wire Compatibility:
   - Verify strict Pydantic v2 schema validity across all responses:
     - TelemetryResponse (including dual-compatibility computed fields: flights, count, airborne, anomalies).
     - FlightDetailResponse (including trail, trail_history, aviation unit conversions).
     - AnomaliesResponse (including events, anomalies alias, total_anomalies, count).
     - SystemStatsResponse (including cache_health diagnostics).
     - HealthResponse (including operational mode and connectivity).
5. Edge State Handling:
   - Verify behavior and schema integrity when cache is completely empty.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import statistics
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pytest
from fastapi.testclient import TestClient

from core.cache import AircraftCache
from core.synthetic import SyntheticReplayGenerator
from main import app
from models.aircraft import FlightState
from models.schemas import (
    AnomaliesResponse,
    CacheHealthStats,
    FlightDetailResponse,
    HealthResponse,
    SystemStatsResponse,
    TelemetryResponse,
)

# Silence verbose httpx request logging during heavy concurrency tests
logging.getLogger("httpx").setLevel(logging.WARNING)


@pytest.fixture(scope="module")
def shared_test_client() -> TestClient:
    """Module-level TestClient for REST endpoint tests."""
    return TestClient(app, raise_server_exceptions=False)


# ============================================================================
# PART 1: HIGH-CONCURRENCY & HIGH-THROUGHPUT LOAD TESTING (200+ REQUESTS)
# ============================================================================

class TestConcurrencyHighThroughputLoad:
    """
    Executes empirical high-concurrency load tests (250+ requests) across all 5 REST endpoints:
    1. /api/telemetry
    2. /api/flight/{icao24}
    3. /api/anomalies
    4. /api/stats
    5. /api/health
    """

    @pytest.mark.asyncio
    async def test_250_concurrent_requests_across_all_5_endpoints_async(self):
        """
        Issues 250 concurrent requests interleaved across all 5 REST endpoints using httpx.AsyncClient.
        Measures individual request latencies and validates:
        - 0 unhandled exceptions / 0 HTTP 500 status codes.
        - p95 latency is strictly < 50.0 ms.
        - Every response conforms strictly to its Pydantic response schema.
        - 404 responses return correct error payload format.
        """
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Warm-up phase
            for _ in range(5):
                await client.get("/api/health")

            # Discover an active flight from telemetry to test valid flight lookups
            telemetry_init = await client.get("/api/telemetry")
            assert telemetry_init.status_code == 200
            aircraft_list = telemetry_init.json().get("aircraft", [])
            valid_icao = aircraft_list[0]["icao24"] if aircraft_list else "fff001"

            # Define test endpoints matrix across all 5 REST routes
            test_cases: List[Tuple[str, int, Optional[type]]] = [
                ("/api/telemetry", 200, TelemetryResponse),
                (f"/api/flight/{valid_icao}", 200, FlightDetailResponse),
                ("/api/flight/ffffff_nonexistent", 404, None),
                ("/api/anomalies", 200, AnomaliesResponse),
                ("/api/stats", 200, SystemStatsResponse),
                ("/api/health", 200, HealthResponse),
            ]

            total_requests = 250
            semaphore = asyncio.Semaphore(15)  # Concurrency limit simulating parallel clients

            async def timed_request(req_id: int) -> Dict[str, Any]:
                endpoint, expected_status, model_cls = test_cases[req_id % len(test_cases)]
                async with semaphore:
                    t_start = time.perf_counter()
                    resp = await client.get(endpoint)
                    t_elapsed_ms = (time.perf_counter() - t_start) * 1000.0

                return {
                    "id": req_id,
                    "endpoint": endpoint,
                    "status_code": resp.status_code,
                    "expected_status": expected_status,
                    "latency_ms": t_elapsed_ms,
                    "json": resp.json(),
                    "model_cls": model_cls,
                }

            tasks = [timed_request(i) for i in range(total_requests)]
            t_total_start = time.perf_counter()
            results = await asyncio.gather(*tasks)
            t_total_elapsed_ms = (time.perf_counter() - t_total_start) * 1000.0

            # 1. Verify 0 unhandled exceptions / 0 HTTP 500 errors
            server_errors = [r for r in results if r["status_code"] >= 500]
            assert len(server_errors) == 0, f"Found {len(server_errors)} HTTP 500 errors: {server_errors[:5]}"

            # 2. Verify status codes match expectation (200 or 404)
            status_mismatches = [r for r in results if r["status_code"] != r["expected_status"]]
            assert len(status_mismatches) == 0, f"Status code mismatches: {status_mismatches[:5]}"

            # 3. Verify response schema validity across every single response
            for r in results:
                if r["expected_status"] == 200 and r["model_cls"] is not None:
                    # Will raise ValidationError if response doesn't conform
                    r["model_cls"].model_validate(r["json"])
                elif r["expected_status"] == 404:
                    assert "detail" in r["json"], f"404 response missing 'detail': {r['json']}"
                    assert "not found" in r["json"]["detail"].lower()

            # 4. Latency SLA verification (< 50.0 ms p95)
            latencies = [r["latency_ms"] for r in results]
            sorted_latencies = sorted(latencies)
            p50_lat = statistics.median(latencies)
            p90_lat = sorted_latencies[int(len(sorted_latencies) * 0.90)]
            p95_lat = sorted_latencies[int(len(sorted_latencies) * 0.95)]
            p99_lat = sorted_latencies[int(len(sorted_latencies) * 0.99)]
            max_lat = max(latencies)
            min_lat = min(latencies)

            print(f"\n--- ASYNC 250 CONCURRENT REST LOAD TEST REPORT ---")
            print(f"Total Requests:     {total_requests}")
            print(f"Total Wall Time:    {t_total_elapsed_ms:.2f} ms")
            print(f"Throughput:         {total_requests / (t_total_elapsed_ms / 1000.0):.1f} req/sec")
            print(f"Min Latency:        {min_lat:.2f} ms")
            print(f"P50 (Median):       {p50_lat:.2f} ms")
            print(f"P90:                {p90_lat:.2f} ms")
            print(f"P95:                {p95_lat:.2f} ms (SLA < 50.0 ms)")
            print(f"P99:                {p99_lat:.2f} ms")
            print(f"Max Latency:        {max_lat:.2f} ms")
            print(f"Zero 500s:          PASSED (0 errors)")

            assert p95_lat < 50.0, f"Async p95 response time ({p95_lat:.2f}ms) exceeded 50.0ms SLA!"

    def test_250_concurrent_requests_threadpool_with_schema_validation(self, shared_test_client: TestClient):
        """
        Executes 250 concurrent requests using ThreadPoolExecutor (8 concurrent worker threads).
        Validates thread-safety of FastAPI handlers, zero 500s, p95 < 50ms SLA, and schema compliance.
        """
        client = shared_test_client

        # Discover active flight
        t_resp = client.get("/api/telemetry")
        assert t_resp.status_code == 200
        aircraft_list = t_resp.json().get("aircraft", [])
        valid_icao = aircraft_list[0]["icao24"] if aircraft_list else "fff001"

        test_cases: List[Tuple[str, int, Optional[type]]] = [
            ("/api/telemetry", 200, TelemetryResponse),
            (f"/api/flight/{valid_icao}", 200, FlightDetailResponse),
            ("/api/flight/missing_target_icao", 404, None),
            ("/api/anomalies", 200, AnomaliesResponse),
            ("/api/stats", 200, SystemStatsResponse),
            ("/api/health", 200, HealthResponse),
        ]

        total_requests = 250

        def execute_single_request(req_id: int) -> Dict[str, Any]:
            endpoint, expected_status, model_cls = test_cases[req_id % len(test_cases)]
            t_start = time.perf_counter()
            resp = client.get(endpoint)
            t_elapsed_ms = (time.perf_counter() - t_start) * 1000.0

            return {
                "id": req_id,
                "endpoint": endpoint,
                "status_code": resp.status_code,
                "expected_status": expected_status,
                "latency_ms": t_elapsed_ms,
                "json": resp.json(),
                "model_cls": model_cls,
            }

        t_wall_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(execute_single_request, range(total_requests)))
        t_wall_elapsed_ms = (time.perf_counter() - t_wall_start) * 1000.0

        # Assertions
        server_errors = [r for r in results if r["status_code"] >= 500]
        assert len(server_errors) == 0, f"Found {len(server_errors)} HTTP 500 errors in threadpool!"

        # Schema validation
        for r in results:
            assert r["status_code"] == r["expected_status"]
            if r["expected_status"] == 200 and r["model_cls"] is not None:
                r["model_cls"].model_validate(r["json"])
            elif r["expected_status"] == 404:
                assert "detail" in r["json"]

        latencies = [r["latency_ms"] for r in results]
        sorted_latencies = sorted(latencies)
        p50_lat = statistics.median(latencies)
        p95_lat = sorted_latencies[int(len(sorted_latencies) * 0.95)]
        max_lat = max(latencies)

        print(f"\n--- THREADPOOL(8) 250 REST LOAD TEST REPORT ---")
        print(f"Total Requests:     {total_requests}")
        print(f"Total Wall Time:    {t_wall_elapsed_ms:.2f} ms")
        print(f"P50 (Median):       {p50_lat:.2f} ms")
        print(f"P95:                {p95_lat:.2f} ms (SLA < 50.0 ms)")
        print(f"Max Latency:        {max_lat:.2f} ms")

        assert p95_lat < 50.0, f"Threadpool p95 response time ({p95_lat:.2f}ms) exceeded 50.0ms SLA!"


# ============================================================================
# PART 2: ROBUSTNESS, SLA UNDER CONTENTION & LARGE SCALE
# ============================================================================

class TestRobustnessAndContentionSLA:
    """
    Stress-tests REST endpoints under high write contention and large cache populations.
    """

    @pytest.mark.asyncio
    async def test_sla_under_continuous_cache_write_contention(self):
        """
        Stress-tests REST API response time while an ingestion worker continuously
        hammers the cache with state updates (1,000 writes/sec in background thread).
        Verifies:
        - AircraftCache RLock synchronization does not block REST serialization.
        - Zero race conditions or dictionary iteration errors.
        - p95 latency remains strictly < 50.0 ms.
        - 0 HTTP 500 responses.
        """
        cache = app.state.cache
        stop_event = asyncio.Event()

        # Background writer simulating high-speed ingestion updates
        async def fast_writer():
            seq = 0
            while not stop_event.is_set():
                seq += 1
                state = FlightState(
                    icao24="contention_flt",
                    callsign=f"WRT{seq % 100:03d}",
                    latitude=48.0 + (seq % 20) * 0.05,
                    longitude=2.0 + (seq % 20) * 0.05,
                    baro_altitude=10000.0 + (seq % 10) * 100.0,
                    velocity=240.0,
                    vertical_rate=0.0,
                    last_contact=time.time(),
                )
                cache.update_vector(state)
                await asyncio.sleep(0.001)

        writer_task = asyncio.create_task(fast_writer())

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            endpoints = [
                "/api/telemetry",
                "/api/flight/contention_flt",
                "/api/anomalies",
                "/api/stats",
                "/api/health",
            ]

            sem = asyncio.Semaphore(15)

            async def fetch_ep(idx: int) -> Tuple[int, float]:
                ep = endpoints[idx % len(endpoints)]
                async with sem:
                    t0 = time.perf_counter()
                    resp = await client.get(ep)
                    dt_ms = (time.perf_counter() - t0) * 1000.0
                    assert resp.status_code == 200, f"Got status {resp.status_code} for {ep}"
                    return resp.status_code, dt_ms

            tasks = [fetch_ep(i) for i in range(250)]
            results = await asyncio.gather(*tasks)

        stop_event.set()
        await writer_task

        latencies = [dt for _, dt in results]
        sorted_lats = sorted(latencies)
        p95_lat = sorted_lats[int(len(sorted_lats) * 0.95)]
        max_lat = max(latencies)

        print(f"\n--- WRITE CONTENTION SLA REPORT (250 REQS) ---")
        print(f"P50: {statistics.median(latencies):.2f} ms")
        print(f"P95: {p95_lat:.2f} ms (SLA < 50.0 ms)")
        print(f"Max: {max_lat:.2f} ms")

        assert p95_lat < 50.0, f"Write contention p95 latency ({p95_lat:.2f}ms) exceeded 50ms SLA!"

    def test_sla_under_large_cache_population(self, shared_test_client: TestClient):
        """
        Validates API latency SLA when cache holds large flight populations.
        1. Tests 300 active flights with full 30-point histories (9,000 vectors) for full /api/telemetry (< 50ms SLA).
        2. Tests 1,500 active flights (45,000 vectors) across /api/flight, /api/stats, /api/health,
           and /api/telemetry?limit=100 to verify all stay strictly < 50ms.
        """
        client = shared_test_client
        original_cache = app.state.cache

        # 1. 300 flights with full 30-point history (9,000 vectors)
        cache_300 = AircraftCache(max_trail_len=30)
        base_time = time.time()
        for idx in range(300):
            icao = f"{idx:06x}"
            for h in range(30):
                fs = FlightState(
                    icao24=icao,
                    callsign=f"SCALE{idx % 500:03d}",
                    latitude=45.0 + (idx % 50) * 0.1,
                    longitude=10.0 + (idx % 100) * 0.1,
                    baro_altitude=10000.0 + h * 10.0,
                    velocity=250.0,
                    vertical_rate=0.0,
                    squawk="1000",
                    true_track=90.0,
                    last_contact=base_time + h * 1.0,
                )
                cache_300.update_vector(fs)

        app.state.cache = cache_300

        try:
            # Benchmark 30 sequential requests to /api/telemetry with 300 flights
            latencies_300 = []
            for _ in range(30):
                t0 = time.perf_counter()
                resp = client.get("/api/telemetry")
                dt = (time.perf_counter() - t0) * 1000.0
                assert resp.status_code == 200
                data = resp.json()
                assert data["total_aircraft"] == 300
                latencies_300.append(dt)

            sorted_lats_300 = sorted(latencies_300)
            p95_300 = sorted_lats_300[int(len(sorted_lats_300) * 0.95)]
            print(f"\n--- LARGE CACHE SCALE (300 FLIGHTS / 9,000 VECTORS) TELEMETRY LATENCY ---")
            print(f"P50:  {statistics.median(latencies_300):.2f} ms")
            print(f"P95:  {p95_300:.2f} ms (SLA < 50.0 ms)")
            print(f"Max:  {max(latencies_300):.2f} ms")

            assert p95_300 < 50.0, f"300-flight telemetry p95 latency ({p95_300:.2f}ms) exceeded 50ms SLA!"

            # 2. Test 1,500 active flights with 30-point histories across individual endpoints
            cache_1500 = AircraftCache(max_trail_len=30)
            for idx in range(1500):
                icao = f"{idx:06x}"
                for h in range(30):
                    fs = FlightState(
                        icao24=icao,
                        callsign=f"SCALE{idx % 500:03d}",
                        latitude=45.0 + (idx % 50) * 0.1,
                        longitude=10.0 + (idx % 100) * 0.1,
                        baro_altitude=10000.0 + h * 10.0,
                        velocity=250.0,
                        vertical_rate=0.0,
                        squawk="1000",
                        true_track=90.0,
                        last_contact=base_time + h * 1.0,
                    )
                    cache_1500.update_vector(fs)

            app.state.cache = cache_1500

            # Test /api/telemetry?limit=100
            lats_limit100 = []
            for _ in range(20):
                t0 = time.perf_counter()
                r = client.get("/api/telemetry?limit=100")
                lats_limit100.append((time.perf_counter() - t0) * 1000.0)
                assert r.status_code == 200
            p95_limit100 = sorted(lats_limit100)[int(len(lats_limit100) * 0.95)]
            assert p95_limit100 < 50.0, f"1500-flight limit=100 p95 ({p95_limit100:.2f}ms) exceeded 50ms SLA!"

            # Test /api/flight/{icao} lookup under 1500 flights
            lats_flight = []
            for _ in range(20):
                t0 = time.perf_counter()
                r = client.get("/api/flight/000000")
                lats_flight.append((time.perf_counter() - t0) * 1000.0)
                assert r.status_code == 200
            p95_flight = sorted(lats_flight)[int(len(lats_flight) * 0.95)]
            assert p95_flight < 50.0, f"Flight lookup under 1500 flights p95 ({p95_flight:.2f}ms) exceeded 50ms SLA!"

            # Test /api/stats under 1500 flights
            lats_stats = []
            for _ in range(20):
                t0 = time.perf_counter()
                r = client.get("/api/stats")
                lats_stats.append((time.perf_counter() - t0) * 1000.0)
                assert r.status_code == 200
            p95_stats = sorted(lats_stats)[int(len(lats_stats) * 0.95)]
            assert p95_stats < 50.0, f"Stats under 1500 flights p95 ({p95_stats:.2f}ms) exceeded 50ms SLA!"

            # Test /api/health under 1500 flights
            lats_health = []
            for _ in range(20):
                t0 = time.perf_counter()
                r = client.get("/api/health")
                lats_health.append((time.perf_counter() - t0) * 1000.0)
                assert r.status_code == 200
            p95_health = sorted(lats_health)[int(len(lats_health) * 0.95)]
            assert p95_health < 50.0, f"Health under 1500 flights p95 ({p95_health:.2f}ms) exceeded 50ms SLA!"

        finally:
            # Restore original cache
            app.state.cache = original_cache


# ============================================================================
# PART 3: 404 STATUS CODE & ICAO ROUTE ROBUSTNESS
# ============================================================================

class TestIcao404HandlingAndPathRobustness:
    """
    Validates correct 404 status code and error schema when querying non-existent ICAO24s.
    Stress-tests edge cases and malformed/adversarial inputs without causing HTTP 500.
    """

    @pytest.mark.parametrize(
        "nonexistent_icao",
        [
            "000000",
            "ffffff",
            "deadbeef",
            "missing1",
            "abcdef12",
            "000000_fake",
            "none",
            "null",
            "undefined",
        ],
    )
    def test_nonexistent_icao_returns_clean_404(self, shared_test_client: TestClient, nonexistent_icao: str):
        """Verifies querying non-existent hex returns HTTP 404 with descriptive detail."""
        resp = shared_test_client.get(f"/api/flight/{nonexistent_icao}")
        assert resp.status_code == 404, f"Expected 404 for {nonexistent_icao}, got {resp.status_code}"

        data = resp.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()
        assert nonexistent_icao.lower() in data["detail"].lower()

    def test_whitespace_and_case_normalization(self, shared_test_client: TestClient):
        """Verifies whitespace padding and mixed case in flight lookups resolve cleanly."""
        telemetry_resp = shared_test_client.get("/api/telemetry")
        assert telemetry_resp.status_code == 200
        aircraft_list = telemetry_resp.json().get("aircraft", [])
        assert len(aircraft_list) > 0
        target_icao = aircraft_list[0]["icao24"]

        # Upper case
        resp_upper = shared_test_client.get(f"/api/flight/{target_icao.upper()}")
        assert resp_upper.status_code == 200
        assert resp_upper.json()["icao24"] == target_icao.lower()

        # Leading / trailing whitespace (URL encoded)
        resp_space = shared_test_client.get(f"/api/flight/%20{target_icao}%20")
        assert resp_space.status_code == 200
        assert resp_space.json()["icao24"] == target_icao.lower()

    @pytest.mark.parametrize(
        "adversarial_path",
        [
            "%20",               # Space only
            "%2F",               # Forward slash
            "..%2F..%2Fetc",     # Path traversal attempt
            "!!!@@@###$$$",      # Special characters
            "1234567890abcdef",  # Overly long string
        ],
    )
    def test_adversarial_icao_inputs_zero_500(self, shared_test_client: TestClient, adversarial_path: str):
        """Verifies malformed or adversarial ICAO paths never produce unhandled 500 errors."""
        resp = shared_test_client.get(f"/api/flight/{adversarial_path}")
        assert resp.status_code in (404, 422, 400), (
            f"Expected 404/422/400 for adversarial path '{adversarial_path}', got {resp.status_code}"
        )
        assert resp.status_code != 500


# ============================================================================
# PART 4: QUERY PARAMETER FUZZING & SCHEMA INTEGRITY
# ============================================================================

class TestQueryParamsFuzzingAndSchemas:
    """
    Validates query parameter edge cases, boundary values, and full schema compliance.
    """

    def test_telemetry_query_param_permutations(self, shared_test_client: TestClient):
        """Verifies /api/telemetry query parameter permutations and schema compliance."""
        client = shared_test_client

        # 1. anomalies_only filter variations
        for val in ["true", "false", "1", "0"]:
            resp = client.get(f"/api/telemetry?anomalies_only={val}")
            assert resp.status_code == 200
            data = resp.json()
            TelemetryResponse.model_validate(data)

        # 2. limit parameter boundary values
        for limit in [1, 5, 10, 100, 1000]:
            resp = client.get(f"/api/telemetry?limit={limit}")
            assert resp.status_code == 200
            data = resp.json()
            parsed = TelemetryResponse.model_validate(data)
            assert len(parsed.aircraft) <= limit

        # 3. Invalid limit parameter (< 1) returns HTTP 422 (never 500)
        resp_invalid = client.get("/api/telemetry?limit=0")
        assert resp_invalid.status_code == 422
        resp_negative = client.get("/api/telemetry?limit=-5")
        assert resp_negative.status_code == 422

    def test_anomalies_query_param_permutations(self, shared_test_client: TestClient):
        """Verifies /api/anomalies query parameter filters and schema compliance."""
        client = shared_test_client

        # 1. Severity filter with various valid and invalid values
        for sev in ["CRITICAL", "critical", "SEVERE", "severe", "WARNING", "UNKNOWN_SEV"]:
            resp = client.get(f"/api/anomalies?severity={sev}")
            assert resp.status_code == 200
            data = resp.json()
            parsed = AnomaliesResponse.model_validate(data)
            if sev == "UNKNOWN_SEV":
                assert len(parsed.events) == 0

        # 2. Limit boundary values
        for limit in [1, 2, 50, 500]:
            resp = client.get(f"/api/anomalies?limit={limit}")
            assert resp.status_code == 200
            data = resp.json()
            parsed = AnomaliesResponse.model_validate(data)
            assert len(parsed.events) <= limit

        # 3. Invalid limit (< 1) returns HTTP 422
        resp_invalid = client.get("/api/anomalies?limit=0")
        assert resp_invalid.status_code == 422

    def test_empty_cache_behavior_all_endpoints(self, shared_test_client: TestClient):
        """
        Verifies that all 5 REST endpoints degrade gracefully and return valid schemas
        when the cache is completely empty (zero aircraft tracked).
        """
        client = shared_test_client
        original_cache = app.state.cache

        empty_cache = AircraftCache(max_trail_len=30)
        app.state.cache = empty_cache

        try:
            # 1. /api/telemetry
            resp_tel = client.get("/api/telemetry")
            assert resp_tel.status_code == 200
            data_tel = resp_tel.json()
            parsed_tel = TelemetryResponse.model_validate(data_tel)
            assert parsed_tel.total_aircraft == 0
            assert parsed_tel.airborne_count == 0
            assert parsed_tel.anomaly_count == 0
            assert len(parsed_tel.aircraft) == 0

            # 2. /api/flight/{icao24}
            resp_flt = client.get("/api/flight/fff001")
            assert resp_flt.status_code == 404

            # 3. /api/anomalies
            resp_anom = client.get("/api/anomalies")
            assert resp_anom.status_code == 200
            data_anom = resp_anom.json()
            parsed_anom = AnomaliesResponse.model_validate(data_anom)
            assert parsed_anom.total_anomalies == 0
            assert len(parsed_anom.events) == 0

            # 4. /api/stats
            resp_stats = client.get("/api/stats")
            assert resp_stats.status_code == 200
            data_stats = resp_stats.json()
            parsed_stats = SystemStatsResponse.model_validate(data_stats)
            assert parsed_stats.total_tracked == 0
            assert parsed_stats.active_airborne == 0
            assert parsed_stats.cache_health.total_entries == 0

            # 5. /api/health
            resp_health = client.get("/api/health")
            assert resp_health.status_code == 200
            data_health = resp_health.json()
            parsed_health = HealthResponse.model_validate(data_health)
            assert parsed_health.cached_flights == 0
        finally:
            app.state.cache = original_cache
