"""
core/synthetic.py - Deterministic Synthetic Flight Replay Generator for AeroPulse.

Provides offline simulation of 40 European commercial flights (35 nominal + 5 scripted anomalies)
with realistic kinematics, spherical Earth coordinate progression, smooth step increments,
and multi-format export (OpenSky 17-tuple, REST API payload, and FlightState domain objects).
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from models.aircraft import FlightState


@dataclass
class SyntheticFlightTemplate:
    """Immutable definition of a flight's initial state and behavioral parameters."""
    icao24: str
    callsign: str
    origin_country: str
    initial_lat: float
    initial_lon: float
    initial_alt: float        # meters
    initial_velocity: float   # m/s
    initial_track: float      # degrees (0.0-360.0)
    initial_vert_rate: float  # m/s
    squawk: str
    is_anomaly: bool = False
    anomaly_type: Optional[str] = None


@dataclass
class SyntheticFlight:
    """Mutable runtime flight state tracking position and kinematics."""
    template: SyntheticFlightTemplate
    lat: float
    lon: float
    altitude_m: float
    velocity_mps: float
    true_track: float
    vertical_rate_mps: float
    squawk: str
    last_contact: float = 0.0

    def step_kinematics(self, dt: float, step_count: int, rng: random.Random) -> None:
        """Advance flight kinematics over interval dt seconds."""
        # 1. Update horizontal coordinates using spherical navigation
        rad_track = math.radians(self.true_track)
        rad_lat = math.radians(self.lat)

        meters_per_deg_lat = 111320.0
        meters_per_deg_lon = 111320.0 * max(0.1, math.cos(rad_lat))

        delta_north_meters = self.velocity_mps * math.cos(rad_track) * dt
        delta_east_meters = self.velocity_mps * math.sin(rad_track) * dt

        self.lat += delta_north_meters / meters_per_deg_lat
        self.lon += delta_east_meters / meters_per_deg_lon

        # 2. Update altitude and handle scripted anomaly dynamics
        if self.template.anomaly_type == "SEVERE_DESCENT":
            self.altitude_m += self.vertical_rate_mps * dt
            # Recycle altitude to maintain continuous demo loop without ground impact
            if self.altitude_m < 2500.0:
                self.altitude_m = 11500.0
        elif self.template.anomaly_type == "OVERSPEED":
            # Maintain low altitude and high speed invariant
            self.altitude_m = 6200.0
            self.velocity_mps = 355.0
            self.vertical_rate_mps = 0.0
        else:
            # Nominal subtle altitude drift
            drift = 2.0 * math.sin(0.05 * step_count + (abs(hash(self.template.icao24)) % 100))
            self.altitude_m = self.template.initial_alt + drift
            self.vertical_rate_mps = drift / max(1.0, dt)

        # 3. Soft Boundary Steering (Keep inside European Bounding Box)
        # Safe inner box: Lat [22.0, 58.0], Lon [-8.0, 38.0]
        if self.lat < 22.0 or self.lat > 58.0 or self.lon < -8.0 or self.lon > 38.0:
            center_lat, center_lon = 48.0, 12.0
            dy = center_lat - self.lat
            dx = (center_lon - self.lon) * math.cos(math.radians(self.lat))
            target_track = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0

            # Smoothly turn toward center (max turn rate 12.0 deg per step)
            track_diff = (target_track - self.true_track + 180.0) % 360.0 - 180.0
            turn = max(-12.0, min(12.0, track_diff))
            self.true_track = (self.true_track + turn + 360.0) % 360.0
        else:
            # Subtle random heading wander for nominal realism (+/- 0.2 deg)
            if not self.template.is_anomaly:
                self.true_track = (self.true_track + rng.uniform(-0.2, 0.2) + 360.0) % 360.0

        # Hard guard to guarantee bounding box confinement
        self.lat = max(20.1, min(59.9, self.lat))
        self.lon = max(-9.9, min(39.9, self.lon))


class SyntheticReplayGenerator:
    """
    Deterministic European Air Traffic Replay Generator.

    Simulates 40 commercial flights including 5 scripted anomalies.
    Guarantees zero false positives on nominal flights and 100% trap triggers on anomaly flights.
    """

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self.rng = random.Random(self.seed)
        self.step_count = 0
        self.current_time = time.time()
        self.flights: List[SyntheticFlight] = []
        self._init_fleet()

    def _init_fleet(self) -> None:
        """Initialize the 40 aircraft fleet templates."""
        templates: List[SyntheticFlightTemplate] = [
            # --- 5 SCRIPTED ANOMALIES ---
            SyntheticFlightTemplate(
                icao24="a07500", callsign="HIJACK1", origin_country="United Kingdom",
                initial_lat=49.50, initial_lon=0.20, initial_alt=10500.0,
                initial_velocity=235.0, initial_track=160.0, initial_vert_rate=0.0,
                squawk="7500", is_anomaly=True, anomaly_type="SQUAWK_7500"
            ),
            SyntheticFlightTemplate(
                icao24="a07600", callsign="NORDO2", origin_country="Germany",
                initial_lat=51.20, initial_lon=9.50, initial_alt=9800.0,
                initial_velocity=225.0, initial_track=85.0, initial_vert_rate=0.0,
                squawk="7600", is_anomaly=True, anomaly_type="SQUAWK_7600"
            ),
            SyntheticFlightTemplate(
                icao24="a07700", callsign="EMRG77", origin_country="France",
                initial_lat=46.80, initial_lon=3.20, initial_alt=8500.0,
                initial_velocity=240.0, initial_track=220.0, initial_vert_rate=-8.0,
                squawk="7700", is_anomaly=True, anomaly_type="SQUAWK_7700"
            ),
            SyntheticFlightTemplate(
                icao24="a00001", callsign="DIVE99", origin_country="Italy",
                initial_lat=43.50, initial_lon=11.50, initial_alt=11200.0,
                initial_velocity=245.0, initial_track=190.0, initial_vert_rate=-25.50,
                squawk="1000", is_anomaly=True, anomaly_type="SEVERE_DESCENT"
            ),
            SyntheticFlightTemplate(
                icao24="a00002", callsign="MACH01", origin_country="Spain",
                initial_lat=39.80, initial_lon=-1.50, initial_alt=6200.0,
                initial_velocity=355.0, initial_track=45.0, initial_vert_rate=0.0,
                squawk="2000", is_anomaly=True, anomaly_type="OVERSPEED"
            ),
            # --- 35 NOMINAL COMMERCIAL AIRLINERS ---
            SyntheticFlightTemplate("40061d", "BAW142", "United Kingdom", 51.47, -0.45, 10668.0, 235.0, 105.0, 0.0, "3412"),
            SyntheticFlightTemplate("39ac24", "AFR228", "France", 49.00, 2.55, 11277.0, 242.0, 140.0, 0.0, "2201"),
            SyntheticFlightTemplate("3c6445", "DLH400", "Germany", 50.03, 8.57, 10972.0, 238.0, 215.0, 0.0, "1000"),
            SyntheticFlightTemplate("484162", "KLM113", "Netherlands", 52.31, 4.76, 10363.0, 230.0, 118.0, 0.0, "2000"),
            SyntheticFlightTemplate("344381", "IBE310", "Spain", 40.48, -3.56, 9753.0, 225.0, 255.0, 0.0, "0415"),
            SyntheticFlightTemplate("4b1812", "SWR502", "Switzerland", 47.45, 8.54, 10668.0, 232.0, 315.0, 0.0, "5512"),
            SyntheticFlightTemplate("4a8520", "SAS781", "Sweden", 59.65, 17.92, 10058.0, 228.0, 205.0, 0.0, "4201"),
            SyntheticFlightTemplate("300185", "AZA610", "Italy", 41.80, 12.24, 11582.0, 245.0, 115.0, 0.0, "1200"),
            SyntheticFlightTemplate("4b8214", "THY182", "Turkey", 41.27, 28.75, 11277.0, 240.0, 295.0, 0.0, "6124"),
            SyntheticFlightTemplate("495143", "TAP432", "Portugal", 38.77, -9.13, 10972.0, 236.0, 35.0, 0.0, "3310"),
            SyntheticFlightTemplate("4ca120", "EIN602", "Ireland", 53.42, -6.27, 9448.0, 220.0, 105.0, 0.0, "1420"),
            SyntheticFlightTemplate("489021", "LOT380", "Poland", 52.16, 20.96, 10668.0, 234.0, 245.0, 0.0, "7000"),
            SyntheticFlightTemplate("440142", "AUA511", "Austria", 48.11, 16.57, 9753.0, 222.0, 260.0, 0.0, "2104"),
            SyntheticFlightTemplate("44cd12", "BEL325", "Belgium", 50.90, 4.48, 10363.0, 230.0, 205.0, 0.0, "1000"),
            SyntheticFlightTemplate("461f04", "FIN145", "Finland", 59.85, 24.96, 11277.0, 242.0, 210.0, 0.0, "5201"),
            SyntheticFlightTemplate("45c829", "NOZ812", "Norway", 59.90, 10.75, 10972.0, 235.0, 215.0, 0.0, "4432"),
            SyntheticFlightTemplate("406b23", "EZY204", "United Kingdom", 51.15, -0.18, 10363.0, 228.0, 175.0, 0.0, "2301"),
            SyntheticFlightTemplate("4ca789", "RYR512", "Ireland", 51.88, 0.23, 9144.0, 218.0, 295.0, 0.0, "1140"),
            SyntheticFlightTemplate("3c4ac6", "EWG981", "Germany", 51.28, 6.76, 10058.0, 226.0, 190.0, 0.0, "3622"),
            SyntheticFlightTemplate("394208", "TVF441", "France", 48.72, 2.36, 8839.0, 215.0, 150.0, 0.0, "0511"),
            SyntheticFlightTemplate("342194", "VLG280", "Spain", 41.29, 2.08, 10668.0, 233.0, 5.0, 0.0, "1724"),
            SyntheticFlightTemplate("478051", "WZZ194", "Hungary", 47.43, 19.25, 10972.0, 237.0, 290.0, 0.0, "4102"),
            SyntheticFlightTemplate("46b412", "ICE540", "Iceland", 58.00, -5.00, 11582.0, 248.0, 125.0, 0.0, "5012"),
            SyntheticFlightTemplate("469231", "ROT301", "Romania", 44.57, 26.08, 10668.0, 235.0, 295.0, 0.0, "6214"),
            SyntheticFlightTemplate("49d102", "CTN410", "Croatia", 45.74, 16.06, 8534.0, 210.0, 315.0, 0.0, "2410"),
            SyntheticFlightTemplate("4bb089", "TAP102", "Portugal", 41.24, -8.68, 8230.0, 205.0, 95.0, 0.0, "0622"),
            SyntheticFlightTemplate("300224", "ITY112", "Italy", 45.45, 9.27, 7925.0, 200.0, 165.0, 0.0, "1312"),
            SyntheticFlightTemplate("485301", "TRA652", "Netherlands", 51.95, 4.44, 10972.0, 236.0, 200.0, 0.0, "4510"),
            SyntheticFlightTemplate("407221", "TOM401", "United Kingdom", 53.35, -2.27, 11277.0, 240.0, 130.0, 0.0, "3214"),
            SyntheticFlightTemplate("4b0114", "EDW280", "Switzerland", 47.45, 8.54, 11887.0, 250.0, 135.0, 0.0, "5402"),
            SyntheticFlightTemplate("440552", "AUA701", "Austria", 48.11, 16.57, 10058.0, 226.0, 325.0, 0.0, "2511"),
            SyntheticFlightTemplate("3c6801", "DLH104", "Germany", 50.03, 8.57, 8534.0, 212.0, 50.0, 0.0, "1000"),
            SyntheticFlightTemplate("39b112", "AFR114", "France", 43.43, 5.21, 10668.0, 234.0, 5.0, 0.0, "2210"),
            SyntheticFlightTemplate("4ca901", "RYR882", "Ireland", 45.67, 9.70, 10363.0, 228.0, 320.0, 0.0, "1152"),
            SyntheticFlightTemplate("400921", "BAW714", "United Kingdom", 51.47, -0.45, 9448.0, 222.0, 145.0, 0.0, "3405"),
        ]

        self.flights = [
            SyntheticFlight(
                template=t,
                lat=t.initial_lat,
                lon=t.initial_lon,
                altitude_m=t.initial_alt,
                velocity_mps=t.initial_velocity,
                true_track=t.initial_track,
                vertical_rate_mps=t.initial_vert_rate,
                squawk=t.squawk,
                last_contact=self.current_time,
            )
            for t in templates
        ]

    def reset(self) -> None:
        """Reset all flights to their original starting conditions."""
        self.rng = random.Random(self.seed)
        self.step_count = 0
        self.current_time = time.time()
        self._init_fleet()

    def step(self, dt: float = 10.0) -> None:
        """Advance the kinematics of all 40 aircraft by dt seconds."""
        self.step_count += 1
        self.current_time += dt
        for flight in self.flights:
            flight.step_kinematics(dt, self.step_count, self.rng)
            flight.last_contact = self.current_time

    def generate_flight_states(self) -> List[FlightState]:
        """Generate typed FlightState domain models for all 40 aircraft."""
        states = []
        for f in self.flights:
            st = FlightState(
                icao24=f.template.icao24,
                callsign=f.template.callsign,
                origin_country=f.template.origin_country,
                longitude=round(f.lon, 4),
                latitude=round(f.lat, 4),
                baro_altitude=round(f.altitude_m, 1),
                velocity=round(f.velocity_mps, 1),
                vertical_rate=round(f.vertical_rate_mps, 2),
                squawk=f.squawk,
                true_track=round(f.true_track, 1),
                on_ground=False,
                last_contact=self.current_time,
                geo_altitude=round(f.altitude_m + 50.0, 1),
            )
            states.append(st)
        return states

    def tick(self, dt: float = 10.0) -> List[FlightState]:
        """Advance simulation by dt seconds and return fresh FlightState models."""
        self.step(dt)
        return self.generate_flight_states()

    def generate_raw_states(self, timestamp: Optional[float] = None) -> List[List[Any]]:
        """
        Produce a list of 17-element OpenSky raw state vector tuples.

        OpenSky Index Mapping:
        [0]  icao24 (str)
        [1]  callsign (str, padded to 8 chars)
        [2]  origin_country (str)
        [3]  time_position (int)
        [4]  last_contact (int)
        [5]  longitude (float)
        [6]  latitude (float)
        [7]  baro_altitude (float)
        [8]  on_ground (bool = False)
        [9]  velocity (float)
        [10] true_track (float)
        [11] vertical_rate (float)
        [12] sensors (None)
        [13] geo_altitude (float)
        [14] squawk (str)
        [15] spi (bool = False)
        [16] position_source (int = 0)
        """
        ts = int(timestamp if timestamp is not None else self.current_time)
        states = []
        for f in self.flights:
            padded_callsign = f"{f.template.callsign:<8}"
            state_row = [
                f.template.icao24,
                padded_callsign,
                f.template.origin_country,
                ts,                            # time_position
                ts,                            # last_contact
                round(f.lon, 4),               # longitude [5]
                round(f.lat, 4),               # latitude [6]
                round(f.altitude_m, 1),        # baro_altitude [7]
                False,                         # on_ground [8]
                round(f.velocity_mps, 1),      # velocity [9]
                round(f.true_track, 1),        # true_track [10]
                round(f.vertical_rate_mps, 2), # vertical_rate [11]
                None,                          # sensors [12]
                round(f.altitude_m + 50.0, 1), # geo_altitude [13]
                f.squawk,                      # squawk [14]
                False,                         # spi [15]
                0,                             # position_source [16]
            ]
            states.append(state_row)
        return states

    def generate_api_payload(self, timestamp: Optional[float] = None) -> Dict[str, Any]:
        """Produce the complete OpenSky REST API response JSON payload."""
        ts = int(timestamp if timestamp is not None else self.current_time)
        return {
            "time": ts,
            "states": self.generate_raw_states(ts)
        }
