"""
tests/test_challenger_m2_1.py - Empirical Adversarial Challenge Suite for Milestone 2.

Author: Challenger 1 (M2: Deterministic Mechanical Anomaly Detection Engine)
Mission:
1. Boundary Precision Fuzzing (infinitesimal floating-point precision, machine epsilon)
2. Compound Anomaly Resolution (simultaneous emergency combinations & supremum ordering)
3. Adversarial Dirty Values (NaN, +/-Inf, None, strings, corrupt types, sabotaged objects)
4. High-Throughput Adversarial Fuzzing (10,000 randomized/adversarial vectors)
"""

import math
import random
import time
from typing import Any, Dict, List, Optional
import pytest

from core.anomaly_engine import (
    DESCENT_RATE_THRESHOLD_MPS,
    OVERSPEED_ALTITUDE_CEILING_M,
    OVERSPEED_VELOCITY_THRESHOLD_MPS,
    MechanicalAnomalyEngine,
)
from core.cache import AircraftCache
from models.aircraft import FlightState
from models.anomaly import AnomalyCategory, AnomalyFlag, AnomalyRecord, AnomalySeverity


# ==============================================================================
# 1. Boundary Precision Fuzzing
# ==============================================================================

class TestBoundaryPrecisionFuzzing:
    """
    Stress-tests threshold boundaries at infinitesimal float deviations and machine epsilon.
    Thresholds:
      - Descent: vertical_rate < -20.32 m/s
      - Speed: velocity > 330.0 m/s
      - Altitude: baro_altitude < 10,000.0 m
    """

    @pytest.mark.parametrize(
        "vr,expected_anomaly",
        [
            (-20.319999, False),  # Infinitesimally above threshold (slower descent)
            (-20.320000, False),  # Exact threshold boundary (must be NOMINAL)
            (-20.320001, True),   # Infinitesimally below threshold (faster descent)
            (-20.33, True),       # Clear descent anomaly
            (-30.0, True),        # Severe descent
            (-100.0, True),       # Extreme descent
            (0.0, False),         # Level flight
            (10.0, False),        # Normal climb
            (20.32, False),       # Positive climb of same magnitude
            (100.0, False),       # Extreme rocket climb
        ],
    )
    def test_descent_boundary_fuzzing(self, vr: float, expected_anomaly: bool):
        state = {"vertical_rate": vr, "last_contact": time.time()}
        flags = MechanicalAnomalyEngine.evaluate(state)
        has_descent = any(f.category == "SEVERE_DESCENT" for f in flags)
        assert has_descent is expected_anomaly, (
            f"Descent {vr} m/s expected anomaly={expected_anomaly}, got {has_descent}"
        )
        if expected_anomaly:
            assert MechanicalAnomalyEngine.resolve_severity(flags) == AnomalySeverity.SEVERE
        else:
            assert MechanicalAnomalyEngine.resolve_severity(flags) == AnomalySeverity.NOMINAL

    def test_descent_machine_epsilon_boundary(self):
        """Test exact IEEE-754 binary64 machine epsilon steps around -20.32."""
        # math.nextafter(-20.32, 0.0) is slightly greater than -20.32 (closer to 0) -> NOMINAL
        vr_above = math.nextafter(-20.32, 0.0)
        assert vr_above > -20.32
        flags_above = MechanicalAnomalyEngine.evaluate({"vertical_rate": vr_above})
        assert len(flags_above) == 0

        # math.nextafter(-20.32, -100.0) is slightly smaller than -20.32 (further below 0) -> SEVERE
        vr_below = math.nextafter(-20.32, -100.0)
        assert vr_below < -20.32
        flags_below = MechanicalAnomalyEngine.evaluate({"vertical_rate": vr_below})
        assert len(flags_below) == 1
        assert flags_below[0].category == "SEVERE_DESCENT"
        assert flags_below[0].severity == AnomalySeverity.SEVERE

    @pytest.mark.parametrize(
        "speed,alt,expected_overspeed",
        [
            # Speed 329.9999 (below 330.0 limit -> all NOMINAL)
            (329.9999, 9999.999, False),
            (329.9999, 10000.000, False),
            (329.9999, 10000.001, False),
            (329.9999, 12000.0, False),

            # Speed 330.0000 (exact threshold -> all NOMINAL)
            (330.0000, 9999.999, False),
            (330.0000, 10000.000, False),
            (330.0000, 10000.001, False),
            (330.0000, 12000.0, False),

            # Speed 330.0001 (exceeds limit -> triggers ONLY if alt < 10000.0)
            (330.0001, 9999.999, True),   # Exceeds speed and below altitude ceiling
            (330.0001, 10000.000, False), # Exact altitude ceiling (NOMINAL)
            (330.0001, 10000.001, False), # Above altitude ceiling (NOMINAL)
            (330.0001, 12000.0, False),   # High altitude supersonic corridor (NOMINAL)

            # Speed 340.0
            (340.0, 9999.999, True),
            (340.0, 10000.000, False),
            (340.0, 10000.001, False),
            (340.0, 12000.0, False),

            # Speed 500.0
            (500.0, 9999.999, True),
            (500.0, 10000.000, False),
            (500.0, 10000.001, False),
            (500.0, 12000.0, False),
        ],
    )
    def test_overspeed_cartesian_grid_fuzzing(self, speed: float, alt: float, expected_overspeed: bool):
        state = {"velocity": speed, "baro_altitude": alt, "last_contact": time.time()}
        flags = MechanicalAnomalyEngine.evaluate(state)
        has_overspeed = any(f.category == "OVERSPEED_OUTLIER" for f in flags)
        assert has_overspeed is expected_overspeed, (
            f"Speed={speed} m/s, Alt={alt} m expected overspeed={expected_overspeed}, got {has_overspeed}"
        )
        if expected_overspeed:
            assert MechanicalAnomalyEngine.resolve_severity(flags) == AnomalySeverity.SEVERE
        else:
            assert MechanicalAnomalyEngine.resolve_severity(flags) == AnomalySeverity.NOMINAL

    def test_overspeed_machine_epsilon_boundary(self):
        """Test exact IEEE-754 binary64 machine epsilon steps for speed and altitude."""
        # Speed: epsilon below 330.0 at 5000m -> NOMINAL
        s_below = math.nextafter(330.0, 0.0)
        flags_sb = MechanicalAnomalyEngine.evaluate({"velocity": s_below, "baro_altitude": 5000.0})
        assert len(flags_sb) == 0

        # Speed: epsilon above 330.0 at 5000m -> SEVERE
        s_above = math.nextafter(330.0, 1000.0)
        flags_sa = MechanicalAnomalyEngine.evaluate({"velocity": s_above, "baro_altitude": 5000.0})
        assert len(flags_sa) == 1
        assert flags_sa[0].category == "OVERSPEED_OUTLIER"

        # Altitude: at speed 350.0 m/s:
        # epsilon below 10,000.0m -> SEVERE
        alt_below = math.nextafter(10000.0, 0.0)
        flags_ab = MechanicalAnomalyEngine.evaluate({"velocity": 350.0, "baro_altitude": alt_below})
        assert len(flags_ab) == 1
        assert flags_ab[0].category == "OVERSPEED_OUTLIER"

        # epsilon above 10,000.0m -> NOMINAL
        alt_above = math.nextafter(10000.0, 20000.0)
        flags_aa = MechanicalAnomalyEngine.evaluate({"velocity": 350.0, "baro_altitude": alt_above})
        assert len(flags_aa) == 0


# ==============================================================================
# 2. Compound Anomaly Resolution & Supremum Ordering
# ==============================================================================

class TestCompoundAnomalyResolution:
    """
    Stress-tests simultaneous combinations of anomalies and strict supremum priority:
    CRITICAL > SEVERE > WARNING > NOMINAL
    """

    def test_all_severity_comparisons_and_operators(self):
        """Verify comprehensive total ordering across all severity tiers."""
        sevs = [
            AnomalySeverity.NOMINAL,
            AnomalySeverity.WARNING,
            AnomalySeverity.SEVERE,
            AnomalySeverity.CRITICAL,
        ]

        # Strict ascending hierarchy
        for i in range(len(sevs)):
            for j in range(len(sevs)):
                if i < j:
                    assert sevs[i] < sevs[j]
                    assert sevs[i] <= sevs[j]
                    assert sevs[j] > sevs[i]
                    assert sevs[j] >= sevs[i]
                    assert sevs[i] != sevs[j]
                elif i == j:
                    assert sevs[i] == sevs[j]
                    assert sevs[i] <= sevs[j]
                    assert sevs[i] >= sevs[j]
                    assert not (sevs[i] < sevs[j])
                    assert not (sevs[i] > sevs[j])

    def test_string_interoperability_in_comparisons(self):
        """Verify AnomalySeverity compares gracefully against string representations."""
        assert AnomalySeverity.CRITICAL > "SEVERE"
        assert AnomalySeverity.CRITICAL >= "CRITICAL"
        assert AnomalySeverity.SEVERE > "WARNING"
        assert AnomalySeverity.WARNING > "NOMINAL"
        assert AnomalySeverity.NOMINAL < "WARNING"
        assert AnomalySeverity.NOMINAL <= "NOMINAL"

    def test_compound_7700_descent_overspeed_triple(self):
        """7700 (CRITICAL) + severe descent (SEVERE) + overspeed (SEVERE) -> CRITICAL."""
        state = {
            "icao24": "comp01",
            "squawk": "7700",
            "vertical_rate": -35.0,
            "velocity": 360.0,
            "baro_altitude": 4000.0,
            "last_contact": time.time(),
        }
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 3
        cats = {f.category for f in flags}
        assert cats == {"SQUAWK_EMERGENCY", "SEVERE_DESCENT", "OVERSPEED_OUTLIER"}
        resolved = MechanicalAnomalyEngine.resolve_severity(flags)
        assert resolved == AnomalySeverity.CRITICAL

    def test_compound_7500_and_descent(self):
        """7500 Hijack (CRITICAL) + severe descent (SEVERE) -> CRITICAL."""
        state = {
            "icao24": "comp02",
            "squawk": "7500",
            "vertical_rate": -25.0,
            "velocity": 250.0,
            "baro_altitude": 8000.0,
            "last_contact": time.time(),
        }
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 2
        assert MechanicalAnomalyEngine.resolve_severity(flags) == AnomalySeverity.CRITICAL

    def test_compound_7500_and_overspeed(self):
        """7500 Hijack (CRITICAL) + overspeed (SEVERE) -> CRITICAL."""
        state = {
            "icao24": "comp03",
            "squawk": "7500",
            "vertical_rate": 0.0,
            "velocity": 350.0,
            "baro_altitude": 6000.0,
            "last_contact": time.time(),
        }
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 2
        assert MechanicalAnomalyEngine.resolve_severity(flags) == AnomalySeverity.CRITICAL

    def test_compound_7600_and_descent(self):
        """7600 Radio Failure (SEVERE) + severe descent (SEVERE) -> SEVERE."""
        state = {
            "icao24": "comp04",
            "squawk": "7600",
            "vertical_rate": -25.0,
            "velocity": 250.0,
            "baro_altitude": 8000.0,
            "last_contact": time.time(),
        }
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 2
        assert MechanicalAnomalyEngine.resolve_severity(flags) == AnomalySeverity.SEVERE

    def test_compound_7600_and_overspeed(self):
        """7600 Radio Failure (SEVERE) + overspeed (SEVERE) -> SEVERE."""
        state = {
            "icao24": "comp05",
            "squawk": "7600",
            "vertical_rate": 0.0,
            "velocity": 340.0,
            "baro_altitude": 5000.0,
            "last_contact": time.time(),
        }
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 2
        assert MechanicalAnomalyEngine.resolve_severity(flags) == AnomalySeverity.SEVERE

    def test_compound_7600_descent_and_overspeed(self):
        """7600 Radio Failure (SEVERE) + descent (SEVERE) + overspeed (SEVERE) -> SEVERE."""
        state = {
            "icao24": "comp06",
            "squawk": "7600",
            "vertical_rate": -28.0,
            "velocity": 345.0,
            "baro_altitude": 5000.0,
            "last_contact": time.time(),
        }
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 3
        assert MechanicalAnomalyEngine.resolve_severity(flags) == AnomalySeverity.SEVERE

    def test_compound_descent_and_overspeed(self):
        """Severe descent (SEVERE) + overspeed (SEVERE) -> SEVERE."""
        state = {
            "icao24": "comp07",
            "vertical_rate": -30.0,
            "velocity": 345.0,
            "baro_altitude": 5000.0,
            "last_contact": time.time(),
        }
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 2
        assert MechanicalAnomalyEngine.resolve_severity(flags) == AnomalySeverity.SEVERE

    def test_resolve_severity_with_custom_warning_tier(self):
        """Verify WARNING tier behaves as expected in supremum resolution."""
        flag_warn = AnomalyFlag(
            category="CUSTOM_SENSOR_WARNING",
            severity=AnomalySeverity.WARNING,
            rationale="Sensor telemetry degraded.",
            timestamp=time.time(),
        )
        flag_severe = AnomalyFlag(
            category="SEVERE_DESCENT",
            severity=AnomalySeverity.SEVERE,
            rationale="Descent rate extreme.",
            timestamp=time.time(),
        )
        flag_crit = AnomalyFlag(
            category="SQUAWK_EMERGENCY",
            severity=AnomalySeverity.CRITICAL,
            rationale="Emergency declared.",
            timestamp=time.time(),
        )

        assert MechanicalAnomalyEngine.resolve_severity([flag_warn]) == AnomalySeverity.WARNING
        assert MechanicalAnomalyEngine.resolve_severity([flag_warn, flag_severe]) == AnomalySeverity.SEVERE
        assert MechanicalAnomalyEngine.resolve_severity([flag_warn, flag_severe, flag_crit]) == AnomalySeverity.CRITICAL
        assert MechanicalAnomalyEngine.resolve_severity([flag_warn, flag_crit]) == AnomalySeverity.CRITICAL

    def test_resolve_severity_input_tolerance(self):
        """Verify resolve_severity safely handles raw strings, empty collections, and mixed items."""
        assert MechanicalAnomalyEngine.resolve_severity([]) == AnomalySeverity.NOMINAL
        assert MechanicalAnomalyEngine.resolve_severity(None) == AnomalySeverity.NOMINAL
        assert MechanicalAnomalyEngine.resolve_severity([None, "invalid", 123]) == AnomalySeverity.NOMINAL
        assert MechanicalAnomalyEngine.resolve_severity(["warning", "critical"]) == AnomalySeverity.CRITICAL
        assert MechanicalAnomalyEngine.resolve_severity(["ANOMALYSEVERITY.SEVERE"]) == AnomalySeverity.SEVERE


# ==============================================================================
# 3. Adversarial Dirty Values & Exception Immunity
# ==============================================================================

class TestAdversarialDirtyValues:
    """
    Passes NaN, +/-Inf, None, empty strings, corrupt types, and malicious objects into
    MechanicalAnomalyEngine.evaluate() to verify ZERO crashes and zero unhandled exceptions.
    """

    @pytest.mark.parametrize(
        "dirty_val",
        [
            float("nan"),
            float("inf"),
            float("-inf"),
            None,
            "",
            "   ",
            "nan",
            "NaN",
            "inf",
            "-inf",
            "+inf",
            "Infinity",
            "-Infinity",
            "null",
            "None",
            [],
            {},
            object(),
        ],
    )
    def test_numeric_fields_dirty_value_immunity(self, dirty_val: Any):
        """Verify each dirty value in each numeric telemetry field produces zero exceptions and zero false alerts."""
        for field in ["vertical_rate", "velocity", "baro_altitude", "last_contact"]:
            payload = {field: dirty_val}
            flags = MechanicalAnomalyEngine.evaluate(payload)
            assert isinstance(flags, list)
            assert len(flags) == 0, f"Dirty value {dirty_val!r} in {field} caused false anomaly: {flags}"

    @pytest.mark.parametrize(
        "dirty_squawk",
        [
            float("nan"),
            float("inf"),
            float("-inf"),
            None,
            "",
            "   ",
            "0000",
            "1200",
            "7000",
            "770",      # Truncated
            "77000",    # Too long
            "07700",    # Leading zero
            "VFR",
            [],
            {},
            object(),
        ],
    )
    def test_squawk_dirty_value_immunity(self, dirty_squawk: Any):
        """Verify dirty squawks produce zero exceptions and zero false emergency alerts."""
        payload = {"squawk": dirty_squawk, "last_contact": time.time()}
        flags = MechanicalAnomalyEngine.evaluate(payload)
        assert isinstance(flags, list)
        assert len(flags) == 0, f"Dirty squawk {dirty_squawk!r} caused false anomaly: {flags}"

    def test_dirty_state_root_inputs(self):
        """Verify evaluate() survives being passed completely corrupt root objects."""
        corrupt_roots = [
            None,
            [],
            [1, 2, 3],
            "corrupt string",
            b"raw bytes",
            12345,
            3.14159,
            True,
            False,
            object(),
            Exception("Root error"),
            lambda: None,
        ]
        for root in corrupt_roots:
            flags = MechanicalAnomalyEngine.evaluate(root)
            assert isinstance(flags, list)
            assert len(flags) == 0

    def test_malicious_object_with_exploding_attributes(self):
        """Verify evaluate() survives hostile objects designed to raise exceptions on access."""

        class ExplodingPropertyObject:
            @property
            def vertical_rate(self):
                raise RuntimeError("Explosion on vertical_rate access!")

            @property
            def velocity(self):
                raise TypeError("Explosion on velocity access!")

            @property
            def baro_altitude(self):
                raise ValueError("Explosion on baro_altitude access!")

            @property
            def squawk(self):
                raise AttributeError("Explosion on squawk access!")

            @property
            def last_contact(self):
                raise ZeroDivisionError("Explosion on last_contact access!")

        obj = ExplodingPropertyObject()
        flags = MechanicalAnomalyEngine.evaluate(obj)
        assert isinstance(flags, list)
        assert len(flags) == 0

    def test_malicious_dict_subclass_with_exploding_get(self):
        """Verify evaluate() survives custom dict subclasses that raise inside get()."""

        class ExplodingDict(dict):
            def get(self, key, default=None):
                raise KeyError(f"Hostile failure on get('{key}')")

        d = ExplodingDict({"vertical_rate": -30.0})
        flags = MechanicalAnomalyEngine.evaluate(d)
        assert isinstance(flags, list)
        assert len(flags) == 0

    def test_extreme_float_magnitudes_without_overflow_crashes(self):
        """Verify evaluate() survives extreme IEEE-754 finite values (1e308, -1e308)."""
        # -1e308 vertical rate: finite float, triggers severe descent, must format without crash
        flags = MechanicalAnomalyEngine.evaluate({"vertical_rate": -1e308})
        assert len(flags) == 1
        assert flags[0].category == "SEVERE_DESCENT"
        assert flags[0].severity == AnomalySeverity.SEVERE
        assert "ft/min" in flags[0].rationale

        # 1e308 velocity at 5000m altitude: finite float, triggers overspeed, must format without crash
        flags = MechanicalAnomalyEngine.evaluate({"velocity": 1e308, "baro_altitude": 5000.0})
        assert len(flags) == 1
        assert flags[0].category == "OVERSPEED_OUTLIER"
        assert flags[0].severity == AnomalySeverity.SEVERE
        assert "knots" in flags[0].rationale


# ==============================================================================
# 4. High-Throughput Adversarial Stress & Fuzzing Harness
# ==============================================================================

class TestHighThroughputAdversarialFuzzing:
    """
    Executes 10,000 randomized adversarial telemetry state vectors through
    MechanicalAnomalyEngine.evaluate() to prove zero crashes, high throughput, and determinism.
    """

    def test_10000_adversarial_vectors_fuzzing(self):
        rng = random.Random(42)
        total_vectors = 10000

        squawk_candidates = [
            None, "", "   ", "7500", "7600", "7700", "1000", "2000", "1200", "7000",
            float("nan"), float("inf"), 7700, 1200, "INVALID", "7700\n",
        ]
        vr_candidates = [
            None, float("nan"), float("inf"), float("-inf"), -20.319999, -20.320000,
            -20.320001, -25.0, -50.0, 0.0, 10.0, 25.0, "corrupt", -1e308,
        ]
        vel_candidates = [
            None, float("nan"), float("inf"), 200.0, 329.9999, 330.0000, 330.0001,
            350.0, 500.0, -10.0, "nan", 1e308,
        ]
        alt_candidates = [
            None, float("nan"), float("inf"), float("-inf"), 0.0, 5000.0, 9999.999,
            10000.000, 10000.001, 12000.0, -500.0, "corrupt",
        ]

        start_time = time.perf_counter()
        exception_count = 0
        anomaly_count = 0

        for _ in range(total_vectors):
            vector = {
                "icao24": f"{rng.randint(0x000000, 0xffffff):06x}",
                "squawk": rng.choice(squawk_candidates),
                "vertical_rate": rng.choice(vr_candidates),
                "velocity": rng.choice(vel_candidates),
                "baro_altitude": rng.choice(alt_candidates),
                "last_contact": time.time(),
            }
            try:
                flags = MechanicalAnomalyEngine.evaluate(vector)
                sev = MechanicalAnomalyEngine.resolve_severity(flags)
                if flags:
                    anomaly_count += 1
                    assert sev in (AnomalySeverity.SEVERE, AnomalySeverity.CRITICAL)
            except Exception as e:
                exception_count += 1

        elapsed = time.perf_counter() - start_time
        throughput = total_vectors / elapsed

        assert exception_count == 0, f"Encountered {exception_count} unhandled exceptions during fuzzing!"
        assert throughput > 10000.0, f"Throughput {throughput:.0f} vectors/sec fell below 10,000 vectors/sec target!"


# ==============================================================================
# 5. AircraftCache Integration Stress with Compound Anomalies
# ==============================================================================

class TestAircraftCacheIntegrationStress:
    """
    Stress-tests AircraftCache under compound anomaly transitions, state clearing,
    and ring-buffer capacity.
    """

    def test_cache_deduplication_and_compound_updates(self):
        cache = AircraftCache(max_anomalies_buffer=50)

        # 1. Start nominal
        s1 = FlightState(
            icao24="4000a1", callsign="TEST01", squawk="1000",
            velocity=220.0, baro_altitude=8000.0, vertical_rate=0.0,
            last_contact=time.time()
        )
        d1 = cache.update_vector(s1)
        assert d1.status == "NOMINAL"
        assert len(cache.get_recent_anomalies()) == 0

        # 2. Transition into 7700 (CRITICAL)
        s2 = FlightState(
            icao24="4000a1", callsign="TEST01", squawk="7700",
            velocity=220.0, baro_altitude=8000.0, vertical_rate=0.0,
            last_contact=time.time() + 10
        )
        d2 = cache.update_vector(s2)
        assert d2.status == "CRITICAL"
        assert len(cache.get_recent_anomalies()) == 1

        # 3. Ongoing 7700 update (no new transition logged)
        s3 = FlightState(
            icao24="4000a1", callsign="TEST01", squawk="7700",
            velocity=220.0, baro_altitude=8000.0, vertical_rate=0.0,
            last_contact=time.time() + 20
        )
        d3 = cache.update_vector(s3)
        assert d3.status == "CRITICAL"
        assert len(cache.get_recent_anomalies()) == 1

        # 4. Compound: Add severe descent while 7700 remains active
        s4 = FlightState(
            icao24="4000a1", callsign="TEST01", squawk="7700",
            velocity=220.0, baro_altitude=8000.0, vertical_rate=-28.0,
            last_contact=time.time() + 30
        )
        d4 = cache.update_vector(s4)
        assert d4.status == "CRITICAL"
        assert len(d4.anomalies) == 2
        # Exactly one new transition logged for SEVERE_DESCENT
        assert len(cache.get_recent_anomalies()) == 2

        # 5. Recovery to nominal
        s5 = FlightState(
            icao24="4000a1", callsign="TEST01", squawk="1000",
            velocity=220.0, baro_altitude=8000.0, vertical_rate=0.0,
            last_contact=time.time() + 40
        )
        d5 = cache.update_vector(s5)
        assert d5.status == "NOMINAL"
        assert len(d5.anomalies) == 0
        assert len(cache.get_recent_anomalies()) == 2

        # 6. Re-trigger 7700
        s6 = FlightState(
            icao24="4000a1", callsign="TEST01", squawk="7700",
            velocity=220.0, baro_altitude=8000.0, vertical_rate=0.0,
            last_contact=time.time() + 50
        )
        d6 = cache.update_vector(s6)
        assert d6.status == "CRITICAL"
        assert len(cache.get_recent_anomalies()) == 3
