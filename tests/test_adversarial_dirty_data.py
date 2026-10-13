"""
tests/test_adversarial_dirty_data.py - Empirical Adversarial Dirty Data Test Suite.
Verifies zero unhandled exceptions across models/aircraft.py, tuple parsing, and caching
under extreme dirty data: None, NaN, +/-Inf, malformed strings, emojis, negative speeds,
and truncated vectors (lengths 0 to 5, and randomized combinations).
"""

import json
import math
import random
import pytest

from core.cache import AircraftCache
from core.ingestion import (
    parse_state_vector,
    safe_float,
    safe_index,
    safe_str,
    sanitize_icao24,
    sanitize_callsign,
    sanitize_squawk,
)
from models.aircraft import FlightState, TrailPoint, AircraftDetail


class TestAdversarialTruncatedVectors:
    """Tests truncated vectors across all lengths 0 through 17."""

    @pytest.mark.parametrize("length", range(18))
    def test_truncated_vector_lengths_no_exceptions(self, length):
        full_sample = [
            "4b1812", "SWR123", "Switzerland", 1725550000, 1725550000,
            8.5412, 47.4515, 10058.4, False, 230.5, 180.2, -2.5,
            None, 10058.4, "1000", False, 0, 0
        ]
        sub_vector = full_sample[:length]
        res = parse_state_vector(sub_vector, server_time=1725550000.0)

        if length < 1:
            assert res is None
        else:
            assert res is not None
            assert res.icao24 == "4b1812"
            if length >= 2:
                assert res.callsign == "SWR123"
            else:
                assert res.callsign == "4B1812"

            cache = AircraftCache()
            detail = cache.update_vector(res)
            assert detail.icao24 == "4b1812"
            # Verify strict RFC 8259 JSON serialization
            serialized = json.dumps(detail.model_dump(), allow_nan=False)
            assert isinstance(serialized, str)


class TestAdversarialExtremeValues:
    """Tests extreme dirty inputs: None, NaN, +/-Inf, Emojis, and Malformed Strings."""

    def test_all_none_and_empty_inputs(self):
        inputs = [
            None,
            [],
            (),
            [None],
            [None] * 5,
            [None] * 17,
            [None] * 30,
            "",
            "4b1812",
            12345,
            3.14159,
            {"icao": "4b1812"},
        ]
        for inp in inputs:
            res = parse_state_vector(inp)
            assert res is None, f"Expected None for input {inp}, got {res}"

    def test_all_nan_and_inf_inputs(self):
        inputs = [
            [math.nan] * 17,
            [float("inf")] * 17,
            [-float("inf")] * 17,
            ["nan"] * 17,
            ["inf"] * 17,
            ["-inf"] * 17,
        ]
        for inp in inputs:
            res = parse_state_vector(inp)
            assert res is None

    def test_nan_and_inf_in_kinematics_with_valid_icao(self):
        dirty_vector = [
            "4b1812", "SWR123", "Switzerland", math.nan, float("inf"),
            math.nan, float("inf"), -float("inf"), False,
            float("nan"), float("inf"), -float("inf"),
            None, float("nan"), "1000", False, 0
        ]
        res = parse_state_vector(dirty_vector, server_time=1725550000.0)
        assert res is not None
        assert res.icao24 == "4b1812"
        assert res.longitude is None
        assert res.latitude is None
        assert res.baro_altitude is None
        assert res.velocity is None
        assert res.vertical_rate is None
        assert res.alt_ft is None
        assert res.speed_kts is None
        assert res.climb_fpm is None

        cache = AircraftCache()
        detail = cache.update_vector(res)
        assert len(detail.trail) == 0
        json_out = json.dumps(detail.model_dump(), allow_nan=False)
        assert isinstance(json_out, str)

    def test_negative_speeds_and_extreme_kinematics(self):
        vector = [
            "4b1812", "REVERSE", "Country", 1725550000, 1725550000,
            10.0, 50.0, -420.0, False, -75.5, -450.0, -35.2,
            None, -400.0, "7700"
        ]
        res = parse_state_vector(vector, server_time=1725550000.0)
        assert res is not None
        assert res.baro_altitude == -420.0
        assert res.velocity == -75.5
        assert res.vertical_rate == -35.2
        assert res.true_track == 270.0  # -450.0 % 360.0 == 270.0
        assert res.alt_ft == pytest.approx(-420.0 * 3.280839895, rel=1e-2)
        assert res.speed_kts == pytest.approx(-75.5 * 1.943844492, rel=1e-2)
        assert res.climb_fpm == pytest.approx(-35.2 * 196.850394, rel=1e-2)

        cache = AircraftCache()
        detail = cache.update_vector(res)
        assert len(detail.trail) == 1
        assert detail.altitude_sparkline[0] == res.alt_ft
        assert detail.speed_sparkline[0] == res.speed_kts
        assert json.dumps(detail.model_dump(), allow_nan=False)

    def test_emojis_and_unicode_in_all_fields(self):
        # Emojis in icao24 must be rejected
        emoji_icao = ["✈️🔥", "CALL", "Country", 1725550000, 1725550000, 10.0, 50.0]
        assert parse_state_vector(emoji_icao) is None

        # Emojis in callsign stripped, country preserved, emoji squawk rejected
        emoji_vector = [
            "4b1812", "✈️FLY🔥99", "🇯🇵 日本 🌍", 1725550000, 1725550000,
            10.0, 50.0, 5000.0, False, 200.0, 90.0, 0.0,
            None, 5000.0, "7️⃣7️⃣0️⃣0️⃣"
        ]
        res = parse_state_vector(emoji_vector)
        assert res is not None
        assert res.icao24 == "4b1812"
        assert res.callsign == "FLY99"
        assert "日本" in res.origin_country
        assert res.squawk is None  # Emojis are non-octal digits, rejected

        cache = AircraftCache()
        detail = cache.update_vector(res)
        assert detail.callsign == "FLY99"
        assert json.dumps(detail.model_dump(), allow_nan=False)

    def test_malformed_squawk_codes_resilience(self):
        valid_icao = "4b1812"
        # Non-octal, letters, negative squawks should be safely rejected without unhandled exception
        bad_squawks = ["8888", "9999", "7788", "ABCD", "-100", "0800", "   ", ""]
        for sq in bad_squawks:
            vec = [valid_icao, "TEST", "C", 100, 100, 10.0, 50.0, 1000.0, False, 200.0, 90.0, 0.0, None, 1000.0, sq]
            res = parse_state_vector(vec)
            assert res is not None
            assert res.squawk is None, f"Squawk {sq} was expected to be rejected, got {res.squawk}"

        # Valid squawks
        good_squawks = ["7700", "7500", "7600", "0120", "0000", "7777", 7700, 120]
        for sq in good_squawks:
            vec = [valid_icao, "TEST", "C", 100, 100, 10.0, 50.0, 1000.0, False, 200.0, 90.0, 0.0, None, 1000.0, sq]
            res = parse_state_vector(vec)
            assert res is not None
            assert res.squawk is not None
            assert len(res.squawk) == 4
            assert all(ch in "01234567" for ch in res.squawk)


class TestAdversarialFuzzing:
    """Fuzzes parse_state_vector and AircraftCache with 1,000 randomized corrupt tuples."""

    def test_randomized_corrupt_fuzzing(self):
        random.seed(1337)
        dirty_atoms = [
            None,
            math.nan,
            float("inf"),
            -float("inf"),
            "",
            "   ",
            "NaN",
            "Inf",
            "-Infinity",
            "null",
            "None",
            "✈️",
            "🔥🔥🔥",
            "🇯🇵",
            "\x00\x01\xff",
            -999999.0,
            999999.0,
            -0.0,
            0,
            True,
            False,
            [],
            {},
            (1, 2),
            b"corrupt_bytes",
            "4b1812",
            "a07500",
            "000001",
            "zzzzzz",
            "7700",
            "8888",
            47.5,
            8.5,
            -185.0,
            185.0,
            -95.0,
            95.0,
        ]

        cache = AircraftCache()
        total_fuzz_iterations = 1000
        parsed_count = 0
        rejected_count = 0

        for _ in range(total_fuzz_iterations):
            vec_len = random.randint(0, 25)
            fuzz_tuple = [random.choice(dirty_atoms) for _ in range(vec_len)]

            try:
                state = parse_state_vector(fuzz_tuple, server_time=1725550000.0)
                if state is not None:
                    parsed_count += 1
                    # Invariant checks on parsed state
                    assert isinstance(state.icao24, str)
                    assert len(state.icao24) <= 6
                    assert state.icao24 == state.icao24.lower()

                    if state.latitude is not None:
                        assert -90.0 <= state.latitude <= 90.0
                    if state.longitude is not None:
                        assert -180.0 <= state.longitude <= 180.0
                    if state.true_track is not None:
                        assert 0.0 <= state.true_track < 360.0

                    # Ingest into cache
                    detail = cache.update_vector(state)
                    assert detail.icao24 == state.icao24
                    assert len(detail.trail) <= 30

                    # Verify strict RFC 8259 JSON serializability (must never raise ValueError)
                    dump = detail.model_dump()
                    s_json = json.dumps(dump, allow_nan=False)
                    assert isinstance(s_json, str)
                else:
                    rejected_count += 1
            except Exception as exc:
                pytest.fail(f"Unhandled exception during fuzzing on vector {fuzz_tuple}: {type(exc).__name__}: {exc}")

        print(f"\n--- FUZZING REPORT ---")
        print(f"Total Fuzz Vectors: {total_fuzz_iterations}")
        print(f"Valid Parsed Vectors: {parsed_count}")
        print(f"Safely Rejected Vectors: {rejected_count}")
        print(f"Unhandled Exceptions: 0")
        assert parsed_count + rejected_count == total_fuzz_iterations
