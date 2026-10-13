"""
tests/test_anomaly_traps.py - Dedicated Unit Test Suite for Mechanical Anomaly Traps.
Verifies boundary conditions, compound triggers, dirty sensory immunity, and cache integration.
"""

import math
import time
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
# 1. Critical Squawk Trap Tests (F-ANO-01..03, F-ANO-07)
# ==============================================================================

class TestCriticalSquawkTraps:
    """Verifies emergency transponder squawk traps 7500, 7600, 7700."""

    def test_squawk_7500_hijack(self):
        state = FlightState(
            icao24="4b0750", callsign="SWR750", squawk="7500",
            velocity=230.0, baro_altitude=9000.0, vertical_rate=0.0,
            last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 1
        f = flags[0]
        assert f.severity == AnomalySeverity.CRITICAL
        assert f.category == "SQUAWK_EMERGENCY"
        assert "7500" in f.rationale
        assert any(k in f.rationale.lower() for k in ["hijack", "unlawful"])
        assert f.trap == "SQUAWK_7500"

    def test_squawk_7600_radio_failure(self):
        state = FlightState(
            icao24="3c0760", callsign="DLH760", squawk="7600",
            velocity=240.0, baro_altitude=10000.0, vertical_rate=0.0,
            last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 1
        f = flags[0]
        assert f.severity == AnomalySeverity.SEVERE
        assert f.category == "SQUAWK_EMERGENCY"
        assert "7600" in f.rationale
        assert any(k in f.rationale.lower() for k in ["radio", "communication", "nordo"])
        assert f.trap == "SQUAWK_7600"

    def test_squawk_7700_general_emergency(self):
        state = FlightState(
            icao24="400770", callsign="BAW770", squawk="7700",
            velocity=220.0, baro_altitude=8000.0, vertical_rate=0.0,
            last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 1
        f = flags[0]
        assert f.severity == AnomalySeverity.CRITICAL
        assert f.category == "SQUAWK_EMERGENCY"
        assert "7700" in f.rationale
        assert "emergency" in f.rationale.lower()
        assert f.trap == "SQUAWK_7700"

    def test_squawk_whitespace_normalization(self):
        state = FlightState(
            icao24="400770", squawk="  7500  ", last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 1
        assert flags[0].severity == AnomalySeverity.CRITICAL
        assert flags[0].category == "SQUAWK_EMERGENCY"

    @pytest.mark.parametrize("code", ["1000", "2000", "1200", "7000", "0000", "7777", "4401", "5201"])
    def test_squawk_nominal_codes_produce_no_anomaly(self, code):
        state = FlightState(
            icao24="3c1234", squawk=code, velocity=220.0,
            baro_altitude=8000.0, vertical_rate=0.0, last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 0


# ==============================================================================
# 2. Severe Descent Vector Trap Tests & Exact Boundaries (F-ANO-04, F-ANO-07)
# ==============================================================================

class TestSevereDescentBoundaries:
    """Verifies strict inequality: vertical_rate < -20.32 m/s."""

    def test_descent_exact_boundary_is_nominal(self):
        state = FlightState(
            icao24="3c0001", vertical_rate=-20.320000, velocity=220.0,
            baro_altitude=8000.0, squawk="1000", last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        descent_flags = [f for f in flags if f.category == "SEVERE_DESCENT"]
        assert len(descent_flags) == 0, "Exact boundary -20.32 m/s must NOT trigger severe descent"

    def test_descent_just_below_boundary_triggers_anomaly(self):
        state = FlightState(
            icao24="3c0002", vertical_rate=-20.320100, velocity=220.0,
            baro_altitude=8000.0, squawk="1000", last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        descent_flags = [f for f in flags if f.category == "SEVERE_DESCENT"]
        assert len(descent_flags) == 1
        assert descent_flags[0].severity == AnomalySeverity.SEVERE
        assert "depressurization" in descent_flags[0].rationale.lower()
        assert descent_flags[0].trap == "SEVERE_DESCENT"

    def test_descent_extreme_dive(self):
        state = FlightState(
            icao24="3c0003", vertical_rate=-35.0, velocity=250.0,
            baro_altitude=5000.0, squawk="1000", last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        descent_flags = [f for f in flags if f.category == "SEVERE_DESCENT"]
        assert len(descent_flags) == 1
        assert "-35" in descent_flags[0].rationale
        assert "ft/min" in descent_flags[0].rationale

    def test_descent_steep_nominal_atc_descent_is_nominal(self):
        # Normal rapid descent (-18.0 m/s = ~3,540 ft/min)
        state = FlightState(
            icao24="3c0004", vertical_rate=-18.0, velocity=220.0,
            baro_altitude=6000.0, squawk="1000", last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 0

    def test_descent_climb_is_nominal(self):
        state = FlightState(
            icao24="3c0005", vertical_rate=25.0, velocity=200.0,
            baro_altitude=4000.0, squawk="1000", last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 0


# ==============================================================================
# 3. Overspeed Outlier Trap Tests & Exact Boundaries (F-ANO-05, F-ANO-07)
# ==============================================================================

class TestOverspeedOutlierBoundaries:
    """Verifies condition: velocity > 330.0 m/s AND baro_altitude < 10,000.0 m."""

    def test_overspeed_exact_velocity_boundary_is_nominal(self):
        state = FlightState(
            icao24="390001", velocity=330.000000, baro_altitude=5000.0,
            vertical_rate=0.0, squawk="1000", last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        overspeed_flags = [f for f in flags if f.category == "OVERSPEED_OUTLIER"]
        assert len(overspeed_flags) == 0

    def test_overspeed_just_above_velocity_boundary_triggers_anomaly(self):
        state = FlightState(
            icao24="390002", velocity=330.001000, baro_altitude=5000.0,
            vertical_rate=0.0, squawk="1000", last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        overspeed_flags = [f for f in flags if f.category == "OVERSPEED_OUTLIER"]
        assert len(overspeed_flags) == 1
        assert overspeed_flags[0].severity == AnomalySeverity.SEVERE
        assert "overspeed" in overspeed_flags[0].rationale.lower()
        assert overspeed_flags[0].trap == "OVERSPEED_OUTLIER"

    def test_overspeed_exact_altitude_ceiling_is_nominal(self):
        state = FlightState(
            icao24="390003", velocity=350.0, baro_altitude=10000.000000,
            vertical_rate=0.0, squawk="1000", last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        overspeed_flags = [f for f in flags if f.category == "OVERSPEED_OUTLIER"]
        assert len(overspeed_flags) == 0, "High velocity at 10,000m exact must be NOMINAL (high-altitude corridor)"

    def test_overspeed_just_below_altitude_ceiling_triggers_anomaly(self):
        state = FlightState(
            icao24="390004", velocity=350.0, baro_altitude=9999.900000,
            vertical_rate=0.0, squawk="1000", last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        overspeed_flags = [f for f in flags if f.category == "OVERSPEED_OUTLIER"]
        assert len(overspeed_flags) == 1
        assert overspeed_flags[0].severity == AnomalySeverity.SEVERE

    def test_overspeed_high_altitude_supersonic_corridor_is_nominal(self):
        state = FlightState(
            icao24="390005", velocity=450.0, baro_altitude=12000.0,
            vertical_rate=0.0, squawk="1000", last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 0

    def test_overspeed_missing_altitude_is_safe(self):
        state = FlightState(
            icao24="390006", velocity=350.0, baro_altitude=None,
            vertical_rate=0.0, squawk="1000", last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 0


# ==============================================================================
# 4. Multi-Factor Severity Resolution & Compound Anomaly Tests (F-ANO-06, F-ANO-09)
# ==============================================================================

class TestMultiFactorResolution:
    """Verifies compound triggers and supremum severity ordering."""

    def test_severity_ordering(self):
        assert AnomalySeverity.NOMINAL < AnomalySeverity.WARNING
        assert AnomalySeverity.WARNING < AnomalySeverity.SEVERE
        assert AnomalySeverity.SEVERE < AnomalySeverity.CRITICAL

        assert AnomalySeverity.CRITICAL > AnomalySeverity.SEVERE
        assert AnomalySeverity.SEVERE > AnomalySeverity.WARNING
        assert AnomalySeverity.WARNING > AnomalySeverity.NOMINAL

        assert AnomalySeverity.CRITICAL >= AnomalySeverity.CRITICAL
        assert AnomalySeverity.NOMINAL <= AnomalySeverity.WARNING

        # Verify max() resolution
        sevs = [AnomalySeverity.WARNING, AnomalySeverity.CRITICAL, AnomalySeverity.SEVERE]
        assert max(sevs) == AnomalySeverity.CRITICAL

    def test_severity_string_comparisons(self):
        assert AnomalySeverity.NOMINAL < "WARNING"
        assert AnomalySeverity.SEVERE >= "SEVERE"
        assert AnomalySeverity.CRITICAL > "SEVERE"

    def test_empty_flags_resolves_nominal(self):
        assert MechanicalAnomalyEngine.resolve_severity([]) == AnomalySeverity.NOMINAL

    def test_compound_7700_and_severe_descent(self):
        state = FlightState(
            icao24="400770", callsign="BAW770", squawk="7700",
            vertical_rate=-28.0, velocity=240.0, baro_altitude=7000.0,
            last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 2
        categories = {f.category for f in flags}
        assert "SQUAWK_EMERGENCY" in categories
        assert "SEVERE_DESCENT" in categories
        assert MechanicalAnomalyEngine.resolve_severity(flags) == AnomalySeverity.CRITICAL

    def test_compound_7500_and_overspeed(self):
        state = FlightState(
            icao24="4b0750", callsign="SWR750", squawk="7500",
            velocity=345.0, baro_altitude=5000.0, vertical_rate=0.0,
            last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 2
        categories = {f.category for f in flags}
        assert "SQUAWK_EMERGENCY" in categories
        assert "OVERSPEED_OUTLIER" in categories
        assert MechanicalAnomalyEngine.resolve_severity(flags) == AnomalySeverity.CRITICAL

    def test_triple_compound_anomaly(self):
        state = FlightState(
            icao24="3c0777", callsign="DLH777", squawk="7700",
            velocity=345.0, baro_altitude=5000.0, vertical_rate=-30.0,
            last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 3
        categories = {f.category for f in flags}
        assert "SQUAWK_EMERGENCY" in categories
        assert "SEVERE_DESCENT" in categories
        assert "OVERSPEED_OUTLIER" in categories
        assert MechanicalAnomalyEngine.resolve_severity(flags) == AnomalySeverity.CRITICAL


# ==============================================================================
# 5. Dirty Data & Sensory Fault Tolerance Tests (F-ANO-06)
# ==============================================================================

class TestDirtySensoryImmunity:
    """Verifies zero unhandled exceptions on dirty, NaN, and Infinite values."""

    def test_dirty_data_all_nones_no_exception(self):
        raw_dict = {
            "icao24": "aabb01", "callsign": None, "origin_country": None,
            "longitude": None, "latitude": None, "baro_altitude": None,
            "velocity": None, "vertical_rate": None, "squawk": None,
            "last_contact": time.time(), "on_ground": False
        }
        flags = MechanicalAnomalyEngine.evaluate(raw_dict)
        assert len(flags) == 0

    def test_dirty_data_nans_and_infinities_no_exception(self):
        dirty_vectors = [
            {"icao24": "nan01", "velocity": float("nan"), "baro_altitude": float("nan"), "vertical_rate": float("nan")},
            {"icao24": "inf01", "velocity": float("inf"), "baro_altitude": float("inf"), "vertical_rate": float("inf")},
            {"icao24": "inf02", "velocity": 200.0, "baro_altitude": 5000.0, "vertical_rate": float("-inf")},
            {"icao24": "str01", "velocity": "NaN", "baro_altitude": "Infinity", "vertical_rate": "-inf"},
        ]
        for d in dirty_vectors:
            flags = MechanicalAnomalyEngine.evaluate(d)
            assert len(flags) == 0

    def test_dirty_raw_dict_without_model(self):
        raw = {
            "icao24": "3c0760", "squawk": "7600", "vertical_rate": -25.0,
            "velocity": 230.0, "baro_altitude": 8000.0
        }
        flags = MechanicalAnomalyEngine.evaluate(raw)
        assert len(flags) == 2

    def test_corrupt_types_no_exception(self):
        corrupt_inputs = [
            None,
            [],
            "not a flight state",
            {"icao24": 12345, "velocity": [1, 2, 3], "baro_altitude": {"alt": 5000}},
            {"icao24": "test", "squawk": True, "vertical_rate": "unparseable_string"}
        ]
        for inp in corrupt_inputs:
            flags = MechanicalAnomalyEngine.evaluate(inp)
            assert isinstance(flags, list)


# ==============================================================================
# 6. Cache Integration & Recent Anomalies Buffer Tests (F-ANO-08, F-ANO-09, F-ANO-10)
# ==============================================================================

class TestCacheAnomalyIntegration:
    """Verifies AircraftCache integration with MechanicalAnomalyEngine."""

    def test_cache_auto_evaluation_on_update(self):
        cache = AircraftCache()
        state = FlightState(
            icao24="400770", callsign="BAW770", squawk="7700",
            velocity=230.0, baro_altitude=8000.0, vertical_rate=0.0,
            last_contact=time.time()
        )
        detail = cache.update_vector(state)
        assert detail.status == "CRITICAL"
        assert detail.has_anomaly is True
        assert len(detail.anomalies) == 1

        recent = cache.get_recent_anomalies()
        assert len(recent) == 1
        assert recent[0].icao24 == "400770"
        assert recent[0].category == "SQUAWK_EMERGENCY"
        assert recent[0].severity == AnomalySeverity.CRITICAL

    def test_cache_recent_anomalies_sliding_buffer_capacity(self):
        cache = AircraftCache(max_anomalies_buffer=50)
        now = time.time()
        for i in range(70):
            st = FlightState(
                icao24=f"4b{i:04x}", callsign=f"TST{i:03d}", squawk="7700",
                velocity=220.0, baro_altitude=8000.0, vertical_rate=0.0,
                last_contact=now + i
            )
            cache.update_vector(st)

        recent = cache.get_recent_anomalies()
        assert len(recent) == 50  # Bounded to capacity 50
        # Newest first
        assert recent[0].icao24 == "4b0045"

    def test_cache_state_transition_deduplication(self):
        cache = AircraftCache()
        now = time.time()
        icao = "3c0999"

        # Tick 1: Squawk 7700 -> First detection, logs to recent_anomalies
        st1 = FlightState(
            icao24=icao, squawk="7700", velocity=220.0,
            baro_altitude=8000.0, vertical_rate=0.0, last_contact=now
        )
        cache.update_vector(st1)
        assert len(cache.get_recent_anomalies()) == 1

        # Tick 2: Same squawk 7700 -> Repeated state, must NOT duplicate in recent_anomalies
        st2 = FlightState(
            icao24=icao, squawk="7700", velocity=220.0,
            baro_altitude=8000.0, vertical_rate=0.0, last_contact=now + 10.0
        )
        cache.update_vector(st2)
        assert len(cache.get_recent_anomalies()) == 1

        # Tick 3: Adds severe descent -> New category, logs severe descent
        st3 = FlightState(
            icao24=icao, squawk="7700", velocity=220.0,
            baro_altitude=7500.0, vertical_rate=-25.0, last_contact=now + 20.0
        )
        cache.update_vector(st3)
        recent = cache.get_recent_anomalies()
        assert len(recent) == 2
        assert recent[0].category == "SEVERE_DESCENT"

        # Tick 4: Levels off and squawk changes to nominal -> Anomalies clear
        st4 = FlightState(
            icao24=icao, squawk="1000", velocity=220.0,
            baro_altitude=3000.0, vertical_rate=0.0, last_contact=now + 30.0
        )
        d4 = cache.update_vector(st4)
        assert d4.status == "NOMINAL"
        assert len(d4.anomalies) == 0
        # Recent log remains persistent
        assert len(cache.get_recent_anomalies()) == 2

    def test_cache_set_anomalies_manual(self):
        cache = AircraftCache()
        st = FlightState(
            icao24="4b1234", squawk="1000", velocity=200.0,
            baro_altitude=5000.0, vertical_rate=0.0, last_contact=time.time()
        )
        cache.update_vector(st)
        flag = AnomalyFlag(
            category="SQUAWK_EMERGENCY",
            severity=AnomalySeverity.CRITICAL,
            rationale="Manual test injection",
            trap="SQUAWK_7700"
        )
        success = cache.set_anomalies("4b1234", [flag], "CRITICAL")
        assert success is True
        detail = cache.get_flight("4b1234")
        assert detail.status == "CRITICAL"
        assert len(detail.anomalies) == 1
        assert len(cache.get_recent_anomalies()) == 1


# ==============================================================================
# 7. Nominal Flight Matrix Tests (F-ANO-07)
# ==============================================================================

class TestNominalFlightMatrix:
    """Verifies that realistic commercial flights across all flight phases evaluate to NOMINAL."""

    @pytest.mark.parametrize(
        "phase,vr,vel,alt,squawk",
        [
            ("Cruise FL380", 0.0, 240.0, 11582.0, "1000"),
            ("High Cruise FL410", 0.0, 250.0, 12496.0, "2000"),
            ("Initial Climb", 12.0, 150.0, 2000.0, "7000"),
            ("Step Climb FL350 to FL370", 8.0, 235.0, 11000.0, "1200"),
            ("Standard En-Route Descent", -12.0, 220.0, 7000.0, "1000"),
            ("Steep ATC Expedited Descent", -18.0, 230.0, 5000.0, "4401"),
            ("Terminal Approach", -4.0, 110.0, 1000.0, "5201"),
            ("Final Approach", -3.5, 75.0, 300.0, "1000"),
            ("Holding Pattern", 0.0, 130.0, 2500.0, "7000"),
            ("High Speed Supersonic Corridor", 0.0, 480.0, 15000.0, "1000"),
        ]
    )
    def test_realistic_flight_phases_produce_zero_false_positives(self, phase, vr, vel, alt, squawk):
        state = FlightState(
            icao24="3c00aa", callsign="TESTPHASE", squawk=squawk,
            vertical_rate=vr, velocity=vel, baro_altitude=alt,
            last_contact=time.time()
        )
        flags = MechanicalAnomalyEngine.evaluate(state)
        assert len(flags) == 0, f"False positive anomaly on flight phase {phase}: {flags}"
        assert MechanicalAnomalyEngine.resolve_severity(flags) == AnomalySeverity.NOMINAL
