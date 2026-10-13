"""
tests/test_synthetic.py - Unit tests verifying SyntheticReplayGenerator invariants.
"""

import pytest
from core.synthetic import SyntheticReplayGenerator


class TestSyntheticReplayGenerator:
    """Verify synthetic flight generation, determinism, and anomaly constraints."""

    def test_initial_fleet_count_and_composition(self):
        gen = SyntheticReplayGenerator(seed=42)
        assert len(gen.flights) == 40

        # Verify 5 anomaly flights present
        anomalies = [f for f in gen.flights if f.template.is_anomaly]
        assert len(anomalies) == 5

        # Verify 35 nominal flights present
        nominals = [f for f in gen.flights if not f.template.is_anomaly]
        assert len(nominals) == 35

    def test_determinism_across_runs(self):
        gen1 = SyntheticReplayGenerator(seed=123)
        gen2 = SyntheticReplayGenerator(seed=123)

        # Advance 10 steps
        for _ in range(10):
            gen1.step(10.0)
            gen2.step(10.0)

        states1 = gen1.generate_raw_states()
        states2 = gen2.generate_raw_states()
        assert states1 == states2

    def test_reset_restores_initial_state(self):
        gen = SyntheticReplayGenerator(seed=42)
        initial_states = gen.generate_raw_states()

        for _ in range(20):
            gen.step(10.0)

        advanced_states = gen.generate_raw_states()
        assert initial_states != advanced_states

        gen.reset()
        reset_states = gen.generate_raw_states()
        assert initial_states == reset_states

    def test_scripted_anomalies_present_and_exact(self):
        gen = SyntheticReplayGenerator(seed=42)
        flights_by_icao = {f.template.icao24: f for f in gen.flights}

        # 1. Squawk 7500 Hijack
        f_7500 = flights_by_icao["a07500"]
        assert f_7500.squawk == "7500"
        assert f_7500.template.callsign == "HIJACK1"

        # 2. Squawk 7600 Radio Failure
        f_7600 = flights_by_icao["a07600"]
        assert f_7600.squawk == "7600"
        assert f_7600.template.callsign == "NORDO2"

        # 3. Squawk 7700 General Emergency
        f_7700 = flights_by_icao["a07700"]
        assert f_7700.squawk == "7700"
        assert f_7700.template.callsign == "EMRG77"

        # 4. Severe Descent
        f_dive = flights_by_icao["a00001"]
        assert f_dive.vertical_rate_mps < -20.32
        assert f_dive.vertical_rate_mps == -25.50

        # 5. Overspeed Outlier
        f_mach = flights_by_icao["a00002"]
        assert f_mach.velocity_mps > 330.0
        assert f_mach.altitude_m < 10000.0

    def test_bounding_box_confinement_over_500_steps(self):
        gen = SyntheticReplayGenerator(seed=42)
        # Advance 500 steps (5,000 seconds of flight)
        for _ in range(500):
            gen.step(10.0)
            for f in gen.flights:
                # Must never exit the European bounding box [20.0, 60.0] lat, [-10.0, 40.0] lon
                assert 20.0 <= f.lat <= 60.0, f"Flight {f.template.icao24} escaped latitude: {f.lat}"
                assert -10.0 <= f.lon <= 40.0, f"Flight {f.template.icao24} escaped longitude: {f.lon}"

    def test_opensky_wire_format_compliance(self):
        gen = SyntheticReplayGenerator(seed=42)
        payload = gen.generate_api_payload()
        assert "time" in payload
        assert "states" in payload
        assert len(payload["states"]) == 40

        first_row = payload["states"][0]
        assert len(first_row) == 17
        assert isinstance(first_row[0], str)   # icao24
        assert isinstance(first_row[1], str)   # callsign
        assert isinstance(first_row[5], float) # lon
        assert isinstance(first_row[6], float) # lat
        assert isinstance(first_row[7], float) # baro_alt
        assert isinstance(first_row[8], bool)  # on_ground
        assert isinstance(first_row[9], float) # velocity

    def test_zero_false_positives_on_nominal_flights(self):
        """Strict verification that 35 nominal flights never trigger false positive anomalies."""
        gen = SyntheticReplayGenerator(seed=42)
        # Advance 100 steps
        for _ in range(100):
            states = gen.tick(10.0)
            for st in states:
                # Skip 5 scripted anomalies
                if st.icao24 in {"a07500", "a07600", "a07700", "a00001", "a00002"}:
                    continue
                # Verify nominal squawk
                assert st.squawk not in {"7500", "7600", "7700"}, f"False positive squawk {st.squawk} on {st.icao24}"
                # Verify nominal vertical rate
                if st.vertical_rate is not None:
                    assert st.vertical_rate >= -20.32, f"False positive descent {st.vertical_rate} on {st.icao24}"
                # Verify nominal speed
                if st.velocity is not None and st.baro_altitude is not None and st.baro_altitude < 10000.0:
                    assert st.velocity <= 330.0, f"False positive overspeed {st.velocity} on {st.icao24}"
