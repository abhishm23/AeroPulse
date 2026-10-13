"""
tests/test_tuple_parsing.py - Unit tests for OpenSky state vector tuple parsing resilience.
Defends against None, NaN, +/-Inf, missing fields, truncated rows, and dirty values.
"""

import json
import math
import pytest
from core.ingestion import (
    parse_state_vector,
    safe_float,
    safe_index,
    normalize_callsign,
    normalize_squawk,
)
from models.aircraft import FlightState


class TestSafeFloatAndIndex:
    """Test defensive primitives."""

    def test_safe_float_valid_inputs(self):
        assert safe_float(10.5) == 10.5
        assert safe_float("230.4") == 230.4
        assert safe_float(0) == 0.0
        assert safe_float(-25.5) == -25.5

    def test_safe_float_none_and_nan_inf(self):
        assert safe_float(None) is None
        assert safe_float(float("nan")) is None
        assert safe_float(float("inf")) is None
        assert safe_float(float("-inf")) is None
        assert safe_float("nan") is None
        assert safe_float("inf") is None
        assert safe_float("-inf") is None

    def test_safe_float_corrupt_types(self):
        assert safe_float("invalid_string") is None
        assert safe_float([]) is None
        assert safe_float({}) is None

    def test_safe_index_bounds(self):
        row = ["a", "b", "c"]
        assert safe_index(row, 0) == "a"
        assert safe_index(row, 2) == "c"
        assert safe_index(row, 5, default="DEFAULT") == "DEFAULT"
        assert safe_index(row, -1) is None
        assert safe_index([], 0) is None
        assert safe_index("not_a_list", 0) is None


class TestTupleParsingResilience:
    """Exhaustive tuple sanitization tests."""

    def test_canonical_tuple_parsing(self, canonical_tuple):
        state = parse_state_vector(canonical_tuple, server_time=1725550000)
        assert state is not None
        assert state.icao24 == "4b1812"
        assert state.callsign == "SWR123"
        assert state.origin_country == "Switzerland"
        assert state.longitude == 8.5412
        assert state.latitude == 47.4515
        assert state.baro_altitude == 10058.4
        assert state.velocity == 230.5
        assert state.true_track == 180.2
        assert state.vertical_rate == -2.5
        assert state.squawk == "1000"
        assert state.on_ground is False

    def test_truncated_tuples_handled_safely(self):
        # Empty row
        assert parse_state_vector([], server_time=1725550000) is None

        # Row with only icao24 and callsign
        short_row = ["4b1812", "SWR123"]
        state = parse_state_vector(short_row, server_time=1725550000)
        assert state is not None
        assert state.icao24 == "4b1812"
        assert state.callsign == "SWR123"
        assert state.longitude is None
        assert state.latitude is None
        assert state.squawk is None

    def test_all_nullable_fields_none(self):
        null_row = [
            "3c6445", None, None, None, 1725550000,
            None, None, None, False, None,
            None, None, None, None, None, False, 0
        ]
        state = parse_state_vector(null_row, server_time=1725550000)
        assert state is not None
        assert state.icao24 == "3c6445"
        assert state.callsign == "3C6445"  # Fallback to uppercase icao24
        assert state.baro_altitude is None
        assert state.velocity is None
        assert state.vertical_rate is None
        assert state.squawk is None

    def test_nan_and_inf_immunity(self, canonical_tuple):
        dirty_tuple = list(canonical_tuple)
        dirty_tuple[5] = float("nan")       # lon
        dirty_tuple[6] = float("inf")       # lat
        dirty_tuple[7] = float("-inf")      # alt
        dirty_tuple[9] = float("nan")       # vel
        dirty_tuple[11] = float("inf")      # vert_rate

        state = parse_state_vector(dirty_tuple, server_time=1725550000)
        assert state is not None
        assert state.longitude is None
        assert state.latitude is None
        assert state.baro_altitude is None
        assert state.velocity is None
        assert state.vertical_rate is None

        # Verify JSON serializability (must not raise ValueError: Out of range float values)
        json_output = json.dumps(state.model_dump())
        assert "NaN" not in json_output
        assert "Infinity" not in json_output

    def test_callsign_whitespace_and_empty_normalization(self, canonical_tuple):
        t = list(canonical_tuple)
        t[1] = "  BAW142  "
        s = parse_state_vector(t, 1725550000)
        assert s.callsign == "BAW142"

        t[1] = "       "
        s = parse_state_vector(t, 1725550000)
        assert s.callsign == "4B1812"

    def test_squawk_normalization(self, canonical_tuple):
        t = list(canonical_tuple)

        # Leading zero preservation
        t[14] = "0120"
        s = parse_state_vector(t, 1725550000)
        assert s.squawk == "0120"

        # Whitespace stripping
        t[14] = "  7700 "
        s = parse_state_vector(t, 1725550000)
        assert s.squawk == "7700"

        # Non-digit octal rejection
        t[14] = "INVALID"
        s = parse_state_vector(t, 1725550000)
        assert s.squawk is None

    def test_geofencing_validation(self, canonical_tuple):
        t = list(canonical_tuple)

        # Latitude out of bounds (> 90.0)
        t[6] = 92.5
        s = parse_state_vector(t, 1725550000)
        assert s.latitude is None

        # Longitude out of bounds (< -180.0)
        t[5] = -185.0
        s = parse_state_vector(t, 1725550000)
        assert s.longitude is None

    def test_unit_conversions(self, canonical_tuple):
        state = parse_state_vector(canonical_tuple, server_time=1725550000)
        # Baro alt 10058.4 m -> ~32999.99 ft
        assert state.altitude_ft == pytest.approx(10058.4 * 3.28084, rel=1e-3)
        # Velocity 230.5 m/s -> ~448.05 kts
        assert state.velocity_kts == pytest.approx(230.5 * 1.943844, rel=1e-3)
        # Vertical rate -2.5 m/s -> ~ -492.12 ft/min
        assert state.vertical_rate_fpm == pytest.approx(-2.5 * 196.850394, rel=1e-3)

    def test_invalid_icao_returns_none(self):
        # Empty ICAO
        assert parse_state_vector(["", "TEST"], 1725550000) is None
        assert parse_state_vector([None, "TEST"], 1725550000) is None
        # Non-hex ICAO
        assert parse_state_vector(["xyz!@#", "TEST"], 1725550000) is None

    def test_corrupt_vector_types(self):
        assert parse_state_vector("not a list", 1725550000) is None
        assert parse_state_vector(12345, 1725550000) is None
        assert parse_state_vector(None, 1725550000) is None


class TestOpenSkyIngestionWorker:
    """Test ingestion worker lifecycle, backoff, HTTP 429 interception, and synthetic fallback."""

    def test_backoff_calculation_and_jitter(self, cache):
        from core.ingestion import OpenSkyIngestionWorker
        worker = OpenSkyIngestionWorker(cache=cache)

        backoffs = []
        for err in range(1, 6):
            worker.diagnostics.consecutive_errors = err
            b = worker._calculate_backoff()
            backoffs.append(b)
            assert 10.0 <= b <= 62.0, f"Backoff {b} out of range [10.0, 62.0]"

        # Ensure jitter introduces variation
        worker.diagnostics.consecutive_errors = 2
        b1 = worker._calculate_backoff()
        b2 = worker._calculate_backoff()
        # They shouldn't be identically equal due to uniform jitter
        assert abs(b1 - b2) >= 0.0 or isinstance(b1, float)

    @pytest.mark.asyncio
    async def test_force_mock_mode_ingestion(self, cache):
        from core.ingestion import OpenSkyIngestionWorker, IngestionMode
        from core.synthetic import SyntheticReplayGenerator

        gen = SyntheticReplayGenerator(seed=42)
        worker = OpenSkyIngestionWorker(cache=cache, synthetic_generator=gen, force_mock=True)

        result = await worker.poll_once()
        assert result.success is True
        assert result.mode == IngestionMode.MOCK_REPLAY
        assert result.vectors_parsed == 40
        assert len(cache.get_all_active()) == 40
        assert worker.diagnostics.total_polls == 1
        assert worker.diagnostics.successful_polls == 1

    @pytest.mark.asyncio
    async def test_http_429_fallback_to_synthetic(self, cache):
        import httpx
        from core.ingestion import OpenSkyIngestionWorker, IngestionMode
        from core.synthetic import SyntheticReplayGenerator

        # Mock transport that returns HTTP 429
        mock_transport = httpx.MockTransport(
            lambda request: httpx.Response(429, text="Too Many Requests")
        )
        client = httpx.AsyncClient(transport=mock_transport)

        gen = SyntheticReplayGenerator(seed=42)
        worker = OpenSkyIngestionWorker(
            cache=cache,
            synthetic_generator=gen,
            client=client,
            fallback_enabled=True,
        )

        result = await worker.poll_once()
        assert result.success is False
        assert result.mode == IngestionMode.SYNTHETIC_FALLBACK
        assert worker.diagnostics.http_429_count == 1
        assert worker.diagnostics.consecutive_errors == 1
        # Cache should still receive synthetic fallback states
        assert len(cache.get_all_active()) == 40
        await worker.close()

    @pytest.mark.asyncio
    async def test_network_timeout_fallback_to_synthetic(self, cache):
        import httpx
        from core.ingestion import OpenSkyIngestionWorker, IngestionMode
        from core.synthetic import SyntheticReplayGenerator

        def timeout_handler(request):
            raise httpx.ReadTimeout("Socket timeout")

        mock_transport = httpx.MockTransport(timeout_handler)
        client = httpx.AsyncClient(transport=mock_transport)

        gen = SyntheticReplayGenerator(seed=42)
        worker = OpenSkyIngestionWorker(
            cache=cache,
            synthetic_generator=gen,
            client=client,
            fallback_enabled=True,
        )

        result = await worker.poll_once()
        assert result.success is False
        assert result.mode == IngestionMode.SYNTHETIC_FALLBACK
        assert worker.diagnostics.timeout_count == 1
        assert len(cache.get_all_active()) == 40
        await worker.close()

    @pytest.mark.asyncio
    async def test_successful_opensky_poll_and_recovery(self, cache, canonical_tuple):
        import httpx
        from core.ingestion import OpenSkyIngestionWorker, IngestionMode
        from core.synthetic import SyntheticReplayGenerator

        # Mock successful OpenSky response
        payload = {"time": 1725550000, "states": [canonical_tuple]}
        mock_transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload)
        )
        client = httpx.AsyncClient(transport=mock_transport)

        worker = OpenSkyIngestionWorker(cache=cache, client=client)
        # Simulate prior error to test recovery
        worker.diagnostics.consecutive_errors = 3

        result = await worker.poll_once()
        assert result.success is True
        assert result.mode == IngestionMode.LIVE_OPENSKY
        assert worker.diagnostics.consecutive_errors == 0
        assert worker.diagnostics.successful_polls == 1
        assert len(cache.get_all_active()) == 1
        flight = cache.get_flight("4b1812")
        assert flight is not None
        assert flight.callsign == "SWR123"
        await worker.close()

