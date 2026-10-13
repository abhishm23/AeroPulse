"""
models/anomaly.py - Mechanical Anomaly Data Models for AeroPulse.
Defines severity tiers, active anomaly flags, and historical anomaly audit records.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AnomalySeverity(str, Enum):
    """
    Hierarchical operational severity levels for flight telemetry anomalies.
    Inherits from str for clean JSON serialization and Enum for type safety.
    """
    NOMINAL = "NOMINAL"
    WARNING = "WARNING"
    SEVERE = "SEVERE"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        """Integer priority rank for supremum comparisons."""
        _RANKS = {
            "NOMINAL": 0,
            "WARNING": 1,
            "SEVERE": 2,
            "CRITICAL": 3,
        }
        return _RANKS.get(self.value, 0)

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, AnomalySeverity):
            return self.rank < other.rank
        if isinstance(other, str):
            try:
                return self.rank < AnomalySeverity(other).rank
            except ValueError:
                return NotImplemented
        return NotImplemented

    def __le__(self, other: Any) -> bool:
        if isinstance(other, AnomalySeverity):
            return self.rank <= other.rank
        if isinstance(other, str):
            try:
                return self.rank <= AnomalySeverity(other).rank
            except ValueError:
                return NotImplemented
        return NotImplemented

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, AnomalySeverity):
            return self.rank > other.rank
        if isinstance(other, str):
            try:
                return self.rank > AnomalySeverity(other).rank
            except ValueError:
                return NotImplemented
        return NotImplemented

    def __ge__(self, other: Any) -> bool:
        if isinstance(other, AnomalySeverity):
            return self.rank >= other.rank
        if isinstance(other, str):
            try:
                return self.rank >= AnomalySeverity(other).rank
            except ValueError:
                return NotImplemented
        return NotImplemented


class AnomalyCategory(str, Enum):
    """Canonical anomaly category identifiers."""
    SQUAWK_EMERGENCY = "SQUAWK_EMERGENCY"
    SEVERE_DESCENT = "SEVERE_DESCENT"
    OVERSPEED_OUTLIER = "OVERSPEED_OUTLIER"


class AnomalyFlag(BaseModel):
    """
    Discrete anomaly alert triggered on an individual ADS-B state vector observation.
    Embedded directly within AircraftDetail.anomalies.
    """
    model_config = ConfigDict(populate_by_name=True, use_enum_values=False)

    category: str = Field(
        ...,
        description="Standardized anomaly category: SQUAWK_EMERGENCY, SEVERE_DESCENT, OVERSPEED_OUTLIER"
    )
    severity: AnomalySeverity = Field(
        ...,
        description="Severity level: CRITICAL, SEVERE, WARNING, or NOMINAL"
    )
    rationale: str = Field(
        ...,
        description="Deterministic human-readable explanation including converted physical values"
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="UTC Unix epoch timestamp of detection"
    )
    trap: Optional[str] = Field(
        None,
        description="Specific mechanical trap identifier (e.g., SQUAWK_7700, SEVERE_DESCENT, OVERSPEED_OUTLIER)"
    )

    @field_validator("category", mode="before")
    @classmethod
    def sanitize_category(cls, v: Any) -> str:
        s = str(v).strip() if v is not None else "UNKNOWN"
        return s.upper()

    @field_validator("severity", mode="before")
    @classmethod
    def sanitize_severity(cls, v: Any) -> AnomalySeverity:
        if isinstance(v, AnomalySeverity):
            return v
        if isinstance(v, str):
            cleaned = v.strip().upper()
            if cleaned.startswith("ANOMALYSEVERITY."):
                cleaned = cleaned.split(".", 1)[1]
            try:
                return AnomalySeverity(cleaned)
            except ValueError:
                return AnomalySeverity.WARNING
        return AnomalySeverity.WARNING

    @field_validator("rationale", mode="before")
    @classmethod
    def sanitize_rationale(cls, v: Any) -> str:
        return str(v).strip() if v is not None else ""


class AnomalyRecord(BaseModel):
    """
    Persistent anomaly event model stored in the cache's recent event log buffer.
    Returned as the payload for GET /api/anomalies.
    """
    model_config = ConfigDict(populate_by_name=True, use_enum_values=False)

    id: str = Field(..., description="Unique event identifier (e.g. anom-1725550000-4b1812-squawk_emergency)")
    icao24: str = Field(..., description="24-bit ICAO aircraft hex transponder address")
    callsign: Optional[str] = Field(None, description="Flight callsign or identifier")
    category: str = Field(..., description="Standardized anomaly category")
    severity: AnomalySeverity = Field(..., description="Severity level")
    rationale: str = Field(..., description="Human-readable rationale string")
    timestamp: float = Field(..., description="UTC Unix epoch timestamp of the event")
    trap: Optional[str] = Field(None, description="Specific mechanical trap identifier")

    @classmethod
    def from_flag(
        cls,
        flag: Any,
        icao24: str,
        callsign: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> AnomalyRecord:
        """Constructs an AnomalyRecord from an active AnomalyFlag, dict, or arbitrary object and flight metadata."""
        clean_icao = icao24.strip().lower() if icao24 else "unknown"

        if isinstance(flag, dict):
            ts = flag.get("timestamp") or flag.get("last_contact") or time.time()
            cat = str(flag.get("category") or flag.get("type") or "ANOMALY")
            sev = flag.get("severity") or flag.get("sev") or AnomalySeverity.WARNING
            rationale = str(flag.get("rationale") or flag.get("description") or f"Anomaly {cat} detected")
            trap = flag.get("trap") or cat
        else:
            ts = getattr(flag, "timestamp", None) or time.time()
            cat = str(getattr(flag, "category", None) or getattr(flag, "type", None) or "ANOMALY")
            sev = getattr(flag, "severity", None) or getattr(flag, "sev", None) or AnomalySeverity.WARNING
            rationale = str(getattr(flag, "rationale", None) or getattr(flag, "description", None) or f"Anomaly {cat} detected")
            trap = getattr(flag, "trap", None) or cat

        cat_suffix = cat.lower().replace(" ", "_")
        generated_id = event_id or f"anom-{int(ts)}-{clean_icao}-{cat_suffix}"

        return cls(
            id=generated_id,
            icao24=clean_icao,
            callsign=callsign.strip().upper() if callsign else clean_icao.upper(),
            category=cat,
            severity=sev,
            rationale=rationale,
            timestamp=float(ts),
            trap=trap,
        )


# Compatibility alias
AnomalyEvent = AnomalyRecord
