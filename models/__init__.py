"""
models package for AeroPulse.
"""

from models.aircraft import (
    AircraftDetail,
    FlightState,
    TrailPoint,
    METERS_TO_FEET,
    MPS_TO_KNOTS,
    MPS_TO_FPM,
)
from models.anomaly import (
    AnomalyCategory,
    AnomalyEvent,
    AnomalyFlag,
    AnomalyRecord,
    AnomalySeverity,
)

__all__ = [
    "AircraftDetail",
    "FlightState",
    "TrailPoint",
    "METERS_TO_FEET",
    "MPS_TO_KNOTS",
    "MPS_TO_FPM",
    "AnomalyCategory",
    "AnomalyEvent",
    "AnomalyFlag",
    "AnomalyRecord",
    "AnomalySeverity",
]
