"""
core/anomaly_engine.py - Deterministic Mechanical Anomaly Detection Engine for AeroPulse.
Pure zero-ML mathematical kinematic threshold traps with multi-factor severity resolution.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Union

from models.aircraft import FlightState
from models.anomaly import AnomalyCategory, AnomalyFlag, AnomalySeverity

# Kinematic Trap Physical Constants
DESCENT_RATE_THRESHOLD_MPS: float = -20.32       # -4,000 ft/min exact threshold
OVERSPEED_VELOCITY_THRESHOLD_MPS: float = 330.0  # > 640 knots structural limit
OVERSPEED_ALTITUDE_CEILING_M: float = 10000.0    # 10,000 meters altitude ceiling

# Unit Conversion Multipliers
MPS_TO_KNOTS: float = 1.943844492
MPS_TO_FPM: float = 196.850394

# Emergency Transponder Squawk Dictionary
SQUAWK_TRAPS: Dict[str, Dict[str, Any]] = {
    "7500": {
        "severity": AnomalySeverity.CRITICAL,
        "trap": "SQUAWK_7500",
        "rationale": "CRITICAL SQUAWK 7500: Unlawful Interference / Hijacking event detected.",
    },
    "7600": {
        "severity": AnomalySeverity.SEVERE,
        "trap": "SQUAWK_7600",
        "rationale": "CRITICAL SQUAWK 7600: Lost Communications / Radio failure (NORDO) reported.",
    },
    "7700": {
        "severity": AnomalySeverity.CRITICAL,
        "trap": "SQUAWK_7700",
        "rationale": "CRITICAL SQUAWK 7700: General In-Flight Emergency declared.",
    },
}


def _is_valid_number(val: Any) -> bool:
    """Check if value is a valid non-NaN, non-Inf real number."""
    if val is None:
        return False
    if isinstance(val, (int, float)):
        return not (math.isnan(val) or math.isinf(val))
    if isinstance(val, str):
        cleaned = val.strip()
        if not cleaned or cleaned.lower() in ("nan", "inf", "-inf", "+inf", "null", "none"):
            return False
        try:
            f = float(cleaned)
            return not (math.isnan(f) or math.isinf(f))
        except (ValueError, TypeError):
            return False
    return False


def _to_float(val: Any) -> Optional[float]:
    """Safely convert value to float, returning None if invalid."""
    if not _is_valid_number(val):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _extract_field(state: Any, field_name: str) -> Any:
    """Safely extract field from FlightState instance, dict, or arbitrary object."""
    if isinstance(state, dict):
        return state.get(field_name)
    val = getattr(state, field_name, None)
    if val is None and hasattr(state, "get") and callable(getattr(state, "get")):
        try:
            val = state.get(field_name)
        except Exception:
            pass
    return val


class MechanicalAnomalyEngine:
    """
    Pure mathematical deterministic anomaly detection engine.
    Applies strict kinematic inequality traps against flight telemetry state vectors.
    """

    @classmethod
    def evaluate(cls, state: Union[FlightState, Dict[str, Any], Any]) -> List[AnomalyFlag]:
        """
        Evaluates a single flight state vector against all kinematic anomaly traps.
        Guaranteed zero unhandled exceptions on dirty, None, NaN, Inf, or malformed inputs.
        """
        flags: List[AnomalyFlag] = []

        try:
            # 1. Resolve observation timestamp
            raw_ts = _extract_field(state, "last_contact")
            ts = _to_float(raw_ts)
            if ts is None:
                raw_ts2 = _extract_field(state, "timestamp")
                ts = _to_float(raw_ts2)
            if ts is None:
                ts = time.time()

            # ------------------------------------------------------------------
            # Trap 1: Critical Transponder Squawk Trap (F-ANO-01..03)
            # ------------------------------------------------------------------
            raw_squawk = _extract_field(state, "squawk")
            if raw_squawk is not None:
                clean_squawk = str(raw_squawk).strip()
                if clean_squawk in SQUAWK_TRAPS:
                    config = SQUAWK_TRAPS[clean_squawk]
                    flags.append(
                        AnomalyFlag(
                            category=AnomalyCategory.SQUAWK_EMERGENCY.value,
                            severity=config["severity"],
                            rationale=config["rationale"],
                            timestamp=ts,
                            trap=config["trap"],
                        )
                    )

            # ------------------------------------------------------------------
            # Trap 2: Severe Descent Vector Trap (F-ANO-04)
            # Condition: vertical_rate < -20.32 m/s (-4,000 ft/min)
            # Strict mathematical inequality: -20.3200 is NOMINAL; < -20.32 triggers SEVERE
            # ------------------------------------------------------------------
            raw_vr = _extract_field(state, "vertical_rate")
            vr = _to_float(raw_vr)
            if vr is not None and vr < DESCENT_RATE_THRESHOLD_MPS:
                rate_fpm = vr * MPS_TO_FPM
                rationale = (
                    f"SEVERE DESCENT VECTOR: Aircraft descending at {rate_fpm:.0f} ft/min "
                    f"({vr:.2f} m/s), exceeding emergency depressurization threshold (-4,000 ft/min)."
                )
                flags.append(
                    AnomalyFlag(
                        category=AnomalyCategory.SEVERE_DESCENT.value,
                        severity=AnomalySeverity.SEVERE,
                        rationale=rationale,
                        timestamp=ts,
                        trap="SEVERE_DESCENT",
                    )
                )

            # ------------------------------------------------------------------
            # Trap 3: Low-Altitude Overspeed Outlier Trap (F-ANO-05)
            # Condition: velocity > 330.0 m/s AND baro_altitude < 10,000.0 m
            # Strict mathematical inequality: 330.0 is NOMINAL, > 330.0 triggers;
            # 10,000.0m is NOMINAL, < 10,000m triggers.
            # ------------------------------------------------------------------
            raw_vel = _extract_field(state, "velocity")
            raw_alt = _extract_field(state, "baro_altitude")
            vel = _to_float(raw_vel)
            alt = _to_float(raw_alt)

            if vel is not None and alt is not None:
                if vel > OVERSPEED_VELOCITY_THRESHOLD_MPS and alt < OVERSPEED_ALTITUDE_CEILING_M:
                    speed_kts = vel * MPS_TO_KNOTS
                    rationale = (
                        f"OVERSPEED OUTLIER: Ground speed {speed_kts:.0f} knots ({vel:.1f} m/s) "
                        f"exceeds maximum structural velocity limit at {alt:.0f} m altitude (< 10,000 m)."
                    )
                    flags.append(
                        AnomalyFlag(
                            category=AnomalyCategory.OVERSPEED_OUTLIER.value,
                            severity=AnomalySeverity.SEVERE,
                            rationale=rationale,
                            timestamp=ts,
                            trap="OVERSPEED_OUTLIER",
                        )
                    )

        except Exception:
            # Defensive guard ensuring zero unhandled exceptions on corrupt data
            return []

        return flags

    # Alias for flexible caller integration
    evaluate_vector = evaluate

    @classmethod
    def resolve_severity(cls, flags: List[Any]) -> AnomalySeverity:
        """
        Multi-factor severity resolution (F-ANO-06):
        Resolves a list of anomaly flags to the maximum severity tier:
        CRITICAL > SEVERE > WARNING > NOMINAL.
        Returns NOMINAL if flags is empty.
        """
        if not flags:
            return AnomalySeverity.NOMINAL

        severities: List[AnomalySeverity] = []
        for f in flags:
            sev = getattr(f, "severity", f)
            if isinstance(sev, AnomalySeverity):
                severities.append(sev)
            elif isinstance(sev, str):
                cleaned = sev.strip().upper()
                if cleaned.startswith("ANOMALYSEVERITY."):
                    cleaned = cleaned.split(".", 1)[1]
                try:
                    severities.append(AnomalySeverity(cleaned))
                except ValueError:
                    pass

        if not severities:
            return AnomalySeverity.NOMINAL

        return max(severities)


# Aliases for framework discovery and backward compatibility
AnomalyEngine = MechanicalAnomalyEngine
