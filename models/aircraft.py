"""
AeroPulse Kinematic Models
Defines immutable state vectors, trail trajectory points, and composite flight details.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

# Mathematical unit conversion constants
METERS_TO_FEET: float = 3.280839895
MPS_TO_KNOTS: float = 1.943844492
MPS_TO_FPM: float = 196.850394


def _clean_float(v: Any) -> Optional[float]:
    """Sanitize float inputs against None, NaN, +/-Inf, empty strings, and type mismatches."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if math.isnan(v) or math.isinf(v):
            return None
        return float(v)
    if isinstance(v, str):
        cleaned = v.strip()
        if not cleaned or cleaned.lower() in ("nan", "inf", "-inf", "+inf", "null", "none"):
            return None
        try:
            f = float(cleaned)
            if math.isnan(f) or math.isinf(f):
                return None
            return f
        except (ValueError, TypeError):
            return None
    return None


class TrailPoint(BaseModel):
    """
    Discrete kinematic trajectory snapshot in an aircraft's sliding-window history.
    Used by the Leaflet HUD for flight path polyline rendering and canvas sparklines.
    """
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    lat: float = Field(..., description="WGS-84 latitude in decimal degrees [-90.0, 90.0]")
    lon: float = Field(..., description="WGS-84 longitude in decimal degrees [-180.0, 180.0]")
    altitude: Optional[float] = Field(None, description="Barometric altitude in meters")
    velocity: Optional[float] = Field(None, description="Horizontal ground speed in m/s")
    vertical_rate: Optional[float] = Field(None, description="Vertical climb/descent rate in m/s")
    heading: Optional[float] = Field(None, description="True track in degrees [0.0, 360.0)")
    timestamp: float = Field(..., description="UTC Unix epoch timestamp of observation")

    @field_validator("lat", mode="before")
    @classmethod
    def validate_lat(cls, v: Any) -> float:
        cleaned = _clean_float(v)
        if cleaned is None or not (-90.0 <= cleaned <= 90.0):
            raise ValueError(f"Invalid latitude: {v}")
        return cleaned

    @field_validator("lon", mode="before")
    @classmethod
    def validate_lon(cls, v: Any) -> float:
        cleaned = _clean_float(v)
        if cleaned is None or not (-180.0 <= cleaned <= 180.0):
            raise ValueError(f"Invalid longitude: {v}")
        return cleaned

    @field_validator("altitude", "velocity", "vertical_rate", "heading", mode="before")
    @classmethod
    def validate_optional_floats(cls, v: Any) -> Optional[float]:
        return _clean_float(v)

    def to_coord(self) -> List[float]:
        """Returns Leaflet-compatible [latitude, longitude] pair."""
        return [self.lat, self.lon]

    @computed_field
    @property
    def alt_ft(self) -> Optional[float]:
        """Altitude converted to feet."""
        if self.altitude is None:
            return None
        return round(self.altitude * METERS_TO_FEET, 1)

    @computed_field
    @property
    def speed_kts(self) -> Optional[float]:
        """Horizontal ground speed converted to knots."""
        if self.velocity is None:
            return None
        return round(self.velocity * MPS_TO_KNOTS, 1)

    # Convenience aliases for field compatibility
    @property
    def baro_altitude(self) -> Optional[float]:
        return self.altitude

    @property
    def speed(self) -> Optional[float]:
        return self.velocity


class FlightState(BaseModel):
    """
    Sanitized point-in-time ADS-B kinematic vector for a single aircraft.
    Constructed from OpenSky Network raw state tuples or synthetic replay vectors.
    """
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    icao24: str = Field(..., description="Unique 24-bit ICAO aircraft transponder address in lowercase hex")
    callsign: Optional[str] = Field(None, description="Cleaned alphanumeric 8-character flight callsign")
    origin_country: Optional[str] = Field(None, description="Country of aircraft registration")
    longitude: Optional[float] = Field(None, description="WGS-84 longitude in decimal degrees [-180.0, 180.0]")
    latitude: Optional[float] = Field(None, description="WGS-84 latitude in decimal degrees [-90.0, 90.0]")
    baro_altitude: Optional[float] = Field(None, description="Barometric altitude in meters")
    velocity: Optional[float] = Field(None, description="Horizontal ground speed in meters per second (m/s)")
    vertical_rate: Optional[float] = Field(None, description="Vertical rate in m/s (positive climb, negative descent)")
    squawk: Optional[str] = Field(None, description="4-digit octal transponder squawk code")
    true_track: Optional[float] = Field(None, description="Heading in degrees clockwise from True North [0.0, 360.0)")
    on_ground: bool = Field(False, description="Surface state flag: True if aircraft is taxiing/on ground")
    last_contact: float = Field(..., description="UTC Unix epoch timestamp of last telemetry reception")
    geo_altitude: Optional[float] = Field(None, description="Geometric / GNSS altitude in meters (optional fallback)")

    @field_validator("icao24", mode="before")
    @classmethod
    def sanitize_icao24(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise ValueError("ICAO24 transponder address must be a non-empty string")
        return v.strip().lower()

    @field_validator("callsign", mode="before")
    @classmethod
    def sanitize_callsign(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip().upper()
        return s if s else None

    @field_validator("squawk", mode="before")
    @classmethod
    def sanitize_squawk(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    @field_validator("latitude", mode="before")
    @classmethod
    def validate_latitude(cls, v: Any) -> Optional[float]:
        cleaned = _clean_float(v)
        if cleaned is None:
            return None
        return cleaned if (-90.0 <= cleaned <= 90.0) else None

    @field_validator("longitude", mode="before")
    @classmethod
    def validate_longitude(cls, v: Any) -> Optional[float]:
        cleaned = _clean_float(v)
        if cleaned is None:
            return None
        return cleaned if (-180.0 <= cleaned <= 180.0) else None

    @field_validator("baro_altitude", "velocity", "vertical_rate", "geo_altitude", mode="before")
    @classmethod
    def validate_kinematic_floats(cls, v: Any) -> Optional[float]:
        return _clean_float(v)

    @field_validator("true_track", mode="before")
    @classmethod
    def normalize_heading(cls, v: Any) -> Optional[float]:
        cleaned = _clean_float(v)
        if cleaned is None:
            return None
        return round(cleaned % 360.0, 1)

    # Unit Conversion Computed Fields
    @computed_field
    @property
    def alt_ft(self) -> Optional[float]:
        """Barometric altitude converted to feet."""
        if self.baro_altitude is None:
            return None
        return round(self.baro_altitude * METERS_TO_FEET, 1)

    @computed_field
    @property
    def speed_kts(self) -> Optional[float]:
        """Horizontal ground speed converted to knots."""
        if self.velocity is None:
            return None
        return round(self.velocity * MPS_TO_KNOTS, 1)

    @computed_field
    @property
    def climb_fpm(self) -> Optional[float]:
        """Vertical climb/descent rate converted to feet per minute."""
        if self.vertical_rate is None:
            return None
        return round(self.vertical_rate * MPS_TO_FPM, 1)

    # Test compatibility aliases
    @property
    def altitude_ft(self) -> Optional[float]:
        return self.alt_ft

    @property
    def velocity_kts(self) -> Optional[float]:
        return self.speed_kts

    @property
    def vertical_rate_fpm(self) -> Optional[float]:
        return self.climb_fpm


class AircraftDetail(BaseModel):
    """
    Composite operational entity combining full current flight state,
    recent sliding-window kinematic trajectory trail (up to 30 points),
    unit-converted aviation values, and active mechanical anomaly flags.
    """
    model_config = ConfigDict(populate_by_name=True)

    icao24: str = Field(..., description="Unique 24-bit ICAO address")
    callsign: Optional[str] = Field(None, description="Flight callsign")
    origin_country: Optional[str] = Field(None, description="Country of registration")
    longitude: Optional[float] = Field(None, description="Current longitude")
    latitude: Optional[float] = Field(None, description="Current latitude")
    baro_altitude: Optional[float] = Field(None, description="Barometric altitude in meters")
    velocity: Optional[float] = Field(None, description="Ground speed in m/s")
    vertical_rate: Optional[float] = Field(None, description="Climb/descent rate in m/s")
    squawk: Optional[str] = Field(None, description="Squawk code")
    true_track: Optional[float] = Field(None, description="Heading in degrees")
    on_ground: bool = Field(False, description="Surface state flag")
    last_contact: float = Field(..., description="Last telemetry contact timestamp")
    geo_altitude: Optional[float] = Field(None, description="Geometric altitude in meters")

    # Kinematic history & operational status
    trail: List[TrailPoint] = Field(default_factory=list, description="Chronological trail points (oldest to newest, max 30)")
    status: str = Field("NOMINAL", description="Operational severity: NOMINAL, WARNING, SEVERE, or CRITICAL")
    anomalies: List[Any] = Field(default_factory=list, description="List of active anomaly event models/records")
    has_anomaly: bool = Field(False, description="Convenience flag: True if status is not NOMINAL")

    # Unit Conversion Computed Fields (Included automatically in model_dump() and JSON)
    @computed_field
    @property
    def speed_kts(self) -> Optional[float]:
        """Horizontal ground speed converted to knots."""
        if self.velocity is None:
            return None
        return round(self.velocity * MPS_TO_KNOTS, 1)

    @computed_field
    @property
    def alt_ft(self) -> Optional[float]:
        """Barometric altitude converted to feet."""
        if self.baro_altitude is None:
            return None
        return round(self.baro_altitude * METERS_TO_FEET, 1)

    @computed_field
    @property
    def climb_fpm(self) -> Optional[float]:
        """Vertical climb/descent rate converted to feet per minute."""
        if self.vertical_rate is None:
            return None
        return round(self.vertical_rate * MPS_TO_FPM, 1)

    # Convenience Helpers for HUD Sparklines and Map Polyline
    @property
    def history(self) -> List[TrailPoint]:
        """Alias for trail history list."""
        return self.trail

    @property
    def trail_history(self) -> List[TrailPoint]:
        """Alias for trail history list."""
        return self.trail

    @property
    def trail_coords(self) -> List[List[float]]:
        """List of [lat, lon] coordinates formatted for Leaflet L.polyline."""
        return [p.to_coord() for p in self.trail]

    @property
    def altitude_sparkline(self) -> List[float]:
        """List of altitude points in feet for HTML5 Canvas sparklines."""
        return [p.alt_ft for p in self.trail if p.alt_ft is not None]

    @property
    def speed_sparkline(self) -> List[float]:
        """List of velocity points in knots for HTML5 Canvas sparklines."""
        return [p.speed_kts for p in self.trail if p.speed_kts is not None]

    @property
    def sparklines(self) -> Dict[str, List[float]]:
        """Dictionary with altitude and speed sparkline points."""
        return {
            "altitude": self.altitude_sparkline,
            "speed": self.speed_sparkline,
        }
