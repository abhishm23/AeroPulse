"""
models/schemas.py - Rich Pydantic v2 schemas for AeroPulse API endpoints.
Defines response envelopes and serialization models for REST and WebSocket services.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, computed_field

from models.aircraft import AircraftDetail, TrailPoint
from models.anomaly import AnomalyRecord, AnomalySeverity


class CacheHealthStats(BaseModel):
    """Diagnostics and memory usage for the in-memory flight cache."""
    model_config = ConfigDict(populate_by_name=True)

    total_entries: int = Field(..., description="Active flights currently cached in memory")
    memory_usage_estimate_kb: float = Field(0.0, description="Estimated cache RAM usage in kilobytes")
    stale_pruned_total: int = Field(0, description="Lifetime total of stale flights evicted by TTL")
    last_ingestion_epoch: Optional[float] = Field(None, description="Timestamp of most recent ingestion cycle")
    last_ingestion_status: str = Field("nominal", description="Ingestion health status string")
    ingestion_latency_ms: float = Field(0.0, description="Execution time of last ingestion poll in milliseconds")


class TelemetryResponse(BaseModel):
    """
    Response envelope for GET /api/telemetry.
    Returns active aircraft vectors, kinematic parameters, anomaly flags, and trail histories.
    """
    model_config = ConfigDict(populate_by_name=True)

    timestamp: float = Field(default_factory=time.time, description="Server snapshot timestamp (epoch seconds)")
    total_aircraft: int = Field(..., description="Total active aircraft tracked in memory cache")
    airborne_count: int = Field(..., description="Count of aircraft currently airborne (on_ground == False)")
    anomaly_count: int = Field(..., description="Count of aircraft with active anomaly flags")
    aircraft: List[AircraftDetail] = Field(..., description="List of active aircraft details and kinematic trails")

    @computed_field
    @property
    def count(self) -> int:
        """Alias for total_aircraft for API client compatibility."""
        return self.total_aircraft

    @computed_field
    @property
    def airborne(self) -> int:
        """Alias for airborne_count for API client compatibility."""
        return self.airborne_count

    @computed_field
    @property
    def anomalies(self) -> int:
        """Alias for anomaly_count for API client compatibility."""
        return self.anomaly_count

    @computed_field
    @property
    def flights(self) -> List[AircraftDetail]:
        """Alias for aircraft for frontend and survey compatibility."""
        return self.aircraft


class FlightDetailResponse(BaseModel):
    """
    Response schema for GET /api/flight/{icao24}.
    Returns comprehensive kinematic history, sliding-window trail points, and anomaly details.
    """
    model_config = ConfigDict(populate_by_name=True)

    icao24: str = Field(..., description="Unique 24-bit ICAO aircraft hex address")
    callsign: Optional[str] = Field(None, description="Flight callsign or identifier")
    origin_country: Optional[str] = Field(None, description="Country of aircraft registration")
    longitude: Optional[float] = Field(None, description="Current WGS-84 longitude")
    latitude: Optional[float] = Field(None, description="Current WGS-84 latitude")
    baro_altitude: Optional[float] = Field(None, description="Barometric altitude in meters")
    velocity: Optional[float] = Field(None, description="Horizontal speed in m/s")
    vertical_rate: Optional[float] = Field(None, description="Climb/descent rate in m/s")
    squawk: Optional[str] = Field(None, description="Transponder squawk code")
    true_track: Optional[float] = Field(None, description="Heading in degrees")
    on_ground: bool = Field(False, description="Surface state flag")
    last_contact: float = Field(..., description="Last telemetry contact timestamp")
    geo_altitude: Optional[float] = Field(None, description="Geometric altitude in meters")

    # Operational status & history
    status: str = Field("NOMINAL", description="Operational severity: NOMINAL, WARNING, SEVERE, CRITICAL")
    has_anomaly: bool = Field(False, description="True if any active anomalies exist")
    anomalies: List[Any] = Field(default_factory=list, description="Active anomaly alerts")
    trail: List[TrailPoint] = Field(default_factory=list, description="Kinematic trajectory history")
    trail_history: List[TrailPoint] = Field(default_factory=list, description="Alias for trail history")

    # Metadata & sparkline metrics
    first_seen: float = Field(default_factory=time.time, description="Timestamp flight first entered cache")
    last_seen: float = Field(default_factory=time.time, description="Timestamp flight last updated in cache")
    samples_count: int = Field(0, description="Total history samples currently retained in buffer")

    # Computed aviation unit conversions
    speed_kts: Optional[float] = Field(None, description="Speed in knots")
    alt_ft: Optional[float] = Field(None, description="Altitude in feet")
    climb_fpm: Optional[float] = Field(None, description="Climb rate in feet per minute")

    # Composite state object for nested consumers
    current_state: Optional[Dict[str, Any]] = Field(None, description="Nested aircraft state object")


class AnomaliesResponse(BaseModel):
    """
    Response schema for GET /api/anomalies.
    Returns audit log of recent anomaly events with timestamps, severity, and rationale.
    """
    model_config = ConfigDict(populate_by_name=True)

    timestamp: float = Field(default_factory=time.time, description="Server query timestamp")
    total_anomalies: int = Field(..., description="Total anomaly records matching filter criteria")
    events: List[AnomalyRecord] = Field(default_factory=list, description="Chronological log of anomaly events")

    @computed_field
    @property
    def count(self) -> int:
        """Alias for total_anomalies."""
        return self.total_anomalies

    @computed_field
    @property
    def anomalies(self) -> List[AnomalyRecord]:
        """Alias for events for client compatibility."""
        return self.events


class SystemStatsResponse(BaseModel):
    """
    Response schema for GET /api/stats.
    Aggregate metrics: active counts, anomalies per category/severity, uptime, and cache health.
    """
    model_config = ConfigDict(populate_by_name=True)

    uptime_seconds: float = Field(..., description="Backend service uptime in seconds")
    total_tracked_lifetime: int = Field(0, description="Total aircraft vector updates processed since startup")
    total_tracked: int = Field(..., description="Current count of aircraft in memory cache")
    active_airborne: int = Field(..., description="Active airborne aircraft count")
    active_count: int = Field(..., description="Active airborne aircraft count alias")
    active_on_ground: int = Field(0, description="Active surface/taxiing aircraft count")
    anomalies_total: int = Field(0, description="Total currently anomalous flights")
    anomalies_by_category: Dict[str, int] = Field(default_factory=dict, description="Anomaly count by category")
    anomalies_by_severity: Dict[str, int] = Field(default_factory=dict, description="Anomaly count by severity tier")
    anomaly_counts: Dict[str, int] = Field(default_factory=dict, description="Alias for anomalies_by_severity")
    cache_size: int = Field(..., description="Total entries currently in cache")
    cache_health: CacheHealthStats = Field(..., description="Cache operational health diagnostics")


class HealthResponse(BaseModel):
    """
    Response schema for GET /api/health.
    System health, ingestion mode (LIVE_OPENSKY vs SYNTHETIC_FALLBACK), and failure counters.
    """
    model_config = ConfigDict(populate_by_name=True)

    status: str = Field(..., description="System health status ('healthy', 'degraded', 'unhealthy')")
    mode: str = Field(..., description="Active ingestion mode: LIVE_OPENSKY, SYNTHETIC_FALLBACK, or MOCK_REPLAY")
    opensky_connected: bool = Field(..., description="True if OpenSky REST API is actively reachable")
    consecutive_api_failures: int = Field(0, description="Consecutive upstream polling failure count")
    last_successful_poll: Optional[float] = Field(None, description="Timestamp of most recent successful poll")
    active_websocket_clients: int = Field(0, description="Number of connected WebSocket telemetry clients")
    cached_flights: int = Field(0, description="Number of aircraft currently stored in cache")
    version: str = Field("1.0.0", description="AeroPulse engine release version")
