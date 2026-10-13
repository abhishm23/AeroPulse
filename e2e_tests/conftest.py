"""
Global Fixtures and Authoritative Data Providers for AeroPulse E2E Testing.

Provides deterministic flight state fixtures, dirty ADS-B tuples, mock OpenSky
payloads, TestClient instances, and an authoritative mathematical oracle.
"""

import math
import time
import warnings
from typing import Dict, List, Any, Optional
import pytest

# Filter third-party deprecation warnings (e.g. Starlette TestClient)
warnings.filterwarnings("ignore", category=DeprecationWarning)

from starlette.testclient import TestClient

from e2e_tests.dynamic_loader import (
    get_fastapi_app,
    get_cache_components,
    get_anomaly_components,
    is_m1_ready,
    is_m2_ready,
    is_m3_ready
)


# ==============================================================================
# 1. Authoritative Mathematical Reference Oracle (ORIGINAL_REQUEST.md)
# ==============================================================================

class AuthoritativeAnomalyOracle:
    """
    Mathematical reference oracle directly derived from ORIGINAL_REQUEST.md:
    - R2.1: Squawk in {"7500", "7600", "7700"}
    - R2.2: Vertical rate < -20.32 m/s (-4,000 ft/min)
    - R2.3: Velocity > 330 m/s (> 640 knots) at baro_altitude < 10,000 m
    """
    
    @staticmethod
    def expected_squawk_anomaly(squawk: Optional[str]) -> bool:
        if squawk is None:
            return False
        clean_squawk = str(squawk).strip()
        return clean_squawk in {"7500", "7600", "7700"}
        
    @staticmethod
    def expected_descent_anomaly(vertical_rate: Optional[float]) -> bool:
        if vertical_rate is None or math.isnan(vertical_rate) or math.isinf(vertical_rate):
            return False
        # Strict mathematical inequality: vertical rate < -20.32 m/s
        return float(vertical_rate) < -20.32
        
    @staticmethod
    def expected_overspeed_anomaly(velocity: Optional[float], altitude: Optional[float]) -> bool:
        if velocity is None or altitude is None:
            return False
        if math.isnan(velocity) or math.isinf(velocity) or math.isnan(altitude) or math.isinf(altitude):
            return False
        # Strict condition: velocity > 330.0 m/s AND baro_altitude < 10000.0 m
        return float(velocity) > 330.0 and float(altitude) < 10000.0
        
    @classmethod
    def evaluate(cls, state_dict: Dict[str, Any]) -> List[str]:
        """Returns list of triggered anomaly category names."""
        triggered = []
        if cls.expected_squawk_anomaly(state_dict.get("squawk")):
            triggered.append("SQUAWK_EMERGENCY")
        if cls.expected_descent_anomaly(state_dict.get("vertical_rate")):
            triggered.append("SEVERE_DESCENT")
        if cls.expected_overspeed_anomaly(state_dict.get("velocity"), state_dict.get("baro_altitude")):
            triggered.append("OVERSPEED_OUTLIER")
        return triggered


@pytest.fixture(scope="session")
def anomaly_oracle() -> AuthoritativeAnomalyOracle:
    return AuthoritativeAnomalyOracle()


# ==============================================================================
# 2. Raw ADS-B State Vector Tuple Fixtures (OpenSky Network Format)
# ==============================================================================

@pytest.fixture
def sample_nominal_tuples() -> List[List[Any]]:
    """
    Realistic 17-element ADS-B tuples for nominal commercial flights over Europe:
    [0] icao24, [1] callsign, [2] country, [3] time_pos, [4] last_contact,
    [5] lon, [6] lat, [7] baro_alt, [8] on_ground, [9] vel, [10] track,
    [11] vert_rate, [12] sensors, [13] geo_alt, [14] squawk, [15] spi, [16] pos_source
    """
    now = int(time.time())
    return [
        # Lufthansa A320 cruising nominal
        ["3c6444", "DLH123  ", "Germany", now - 2, now, 8.54, 50.03, 10668.0, False, 235.0, 90.0, 0.0, None, 10800.0, "1000", False, 0],
        # British Airways B777 cruising nominal
        ["400a12", "BAW456  ", "United Kingdom", now - 1, now, 2.35, 48.85, 11582.0, False, 250.0, 180.0, 0.0, None, 11700.0, "2000", False, 0],
        # Air France A350 standard climb
        ["3949ee", "AFR789  ", "France", now - 3, now, 4.89, 45.76, 8000.0, False, 220.0, 270.0, 12.5, None, 8200.0, "7000", False, 0],
        # KLM B737 standard approach descent (-6.5 m/s = ~1280 ft/min)
        ["484123", "KLM321  ", "Netherlands", now - 2, now, 4.76, 52.31, 2500.0, False, 140.0, 45.0, -6.5, None, 2600.0, "4401", False, 0],
        # Swiss A220 cruising nominal
        ["4b1812", "SWR134  ", "Switzerland", now - 1, now, 8.54, 47.45, 9753.0, False, 215.0, 284.0, 0.0, None, 9900.0, "1000", False, 0]
    ]


@pytest.fixture
def sample_emergency_tuples() -> List[List[Any]]:
    """Emergency ADS-B tuples covering squawk 7500, 7600, 7700."""
    now = int(time.time())
    return [
        # Squawk 7500 - Hijack / Unlawful Interference
        ["4b0750", "SWR750  ", "Switzerland", now - 2, now, 8.2, 47.1, 9500.0, False, 230.0, 180.0, 0.0, None, 9600.0, "7500", False, 0],
        # Squawk 7600 - Radio Communication Failure
        ["3c0760", "DLH760  ", "Germany", now - 2, now, 9.1, 48.2, 10000.0, False, 240.0, 90.0, 0.0, None, 10100.0, "7600", False, 0],
        # Squawk 7700 - General Emergency
        ["400770", "BAW770  ", "United Kingdom", now - 2, now, 1.2, 51.5, 7500.0, False, 210.0, 270.0, 0.0, None, 7600.0, "7700", False, 0]
    ]


@pytest.fixture
def sample_severe_descent_tuples() -> List[List[Any]]:
    """Severe descent vectors violating the -20.32 m/s (-4,000 ft/min) threshold."""
    now = int(time.time())
    return [
        # Just below threshold: -20.33 m/s
        ["3c0001", "DLH001  ", "Germany", now - 1, now, 10.0, 52.0, 8000.0, False, 220.0, 180.0, -20.33, None, 8100.0, "1000", False, 0],
        # Rapid depressurization descent: -28.5 m/s (~5,610 ft/min)
        ["3c0002", "DLH002  ", "Germany", now - 1, now, 10.5, 52.5, 6500.0, False, 240.0, 180.0, -28.50, None, 6600.0, "1000", False, 0],
        # Extreme dive: -35.0 m/s (~6,890 ft/min)
        ["3c0003", "DLH003  ", "Germany", now - 1, now, 11.0, 53.0, 5000.0, False, 250.0, 180.0, -35.00, None, 5100.0, "1000", False, 0]
    ]


@pytest.fixture
def sample_overspeed_tuples() -> List[List[Any]]:
    """Overspeed outlier vectors (> 330 m/s at altitude < 10,000m)."""
    now = int(time.time())
    return [
        # Just above threshold: 330.1 m/s at 5,000 m
        ["390001", "AFR001  ", "France", now - 1, now, 2.0, 48.0, 5000.0, False, 330.1, 90.0, 0.0, None, 5100.0, "1000", False, 0],
        # Extreme low-altitude overspeed: 345.0 m/s at 4,000 m
        ["390002", "AFR002  ", "France", now - 1, now, 2.5, 48.5, 4000.0, False, 345.0, 90.0, 0.0, None, 4100.0, "1000", False, 0],
        # Near altitude ceiling: 340.0 m/s at 9,990 m
        ["390003", "AFR003  ", "France", now - 1, now, 3.0, 49.0, 9990.0, False, 340.0, 90.0, 0.0, None, 10100.0, "1000", False, 0]
    ]


@pytest.fixture
def sample_dirty_tuples() -> List[List[Any]]:
    """Adversarial dirty ADS-B tuples with missing, NaN, Inf, and type-mismatched fields."""
    now = int(time.time())
    return [
        # All Nones except mandatory ICAO24 and timestamp
        ["aabb01", None, "Unknown", None, now, None, None, None, False, None, None, None, None, None, None, False, 0],
        # NaNs in numeric fields
        ["aabb02", "NAN001  ", "Germany", now, now, float("nan"), float("nan"), float("nan"), False, float("nan"), float("nan"), float("nan"), None, float("nan"), "1000", False, 0],
        # Positive and negative Infinities
        ["aabb03", "INF001  ", "France", now, now, 2.0, 48.0, float("inf"), False, float("inf"), 90.0, float("-inf"), None, float("inf"), "1000", False, 0],
        # Stringified numeric values and whitespace
        ["aabb04", "  STR001  ", "United Kingdom", now, now, 0.0, 51.0, "8500.0", False, "220.0", "180.0", "-5.0", None, 8600.0, " 1000 ", False, 0],
        # Short truncated tuple (< 17 elements)
        ["aabb05", "SHORT1  ", "Spain", now, now, -3.0, 40.0, 5000.0, False, 200.0]
    ]


# ==============================================================================
# 3. Application & Cache Fixtures
# ==============================================================================

@pytest.fixture
def app_client():
    """
    Provides a Starlette/FastAPI TestClient if main.app is implemented.
    Returns None if backend is not yet built.
    """
    app = get_fastapi_app()
    if app is None:
        return None
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def initialized_cache():
    """
    Creates and yields an instance of AircraftCache/FlightCache if M1 is ready.
    """
    cache_cls, _ = get_cache_components()
    if cache_cls is None:
        return None
    try:
        return cache_cls(max_trail_points=30)
    except TypeError:
        return cache_cls()
