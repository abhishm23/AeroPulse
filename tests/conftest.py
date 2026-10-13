import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import time
import pytest
from typing import Any, List

from core.cache import AircraftCache
from core.synthetic import SyntheticReplayGenerator


@pytest.fixture
def cache() -> AircraftCache:
    """Fresh AircraftCache instance."""
    return AircraftCache(max_trail_len=30)


@pytest.fixture
def synthetic_gen() -> SyntheticReplayGenerator:
    """Deterministic SyntheticReplayGenerator initialized with seed 42."""
    return SyntheticReplayGenerator(seed=42)


@pytest.fixture
def canonical_tuple() -> List[Any]:
    """Realistic 17-element OpenSky ADS-B state vector tuple."""
    now = int(time.time())
    return [
        "4b1812",       # 0: icao24
        "SWR123  ",     # 1: callsign
        "Switzerland",  # 2: origin_country
        now - 2,        # 3: time_position
        now,            # 4: last_contact
        8.5412,         # 5: longitude
        47.4515,        # 6: latitude
        10058.4,        # 7: baro_altitude
        False,          # 8: on_ground
        230.5,          # 9: velocity
        180.2,          # 10: true_track
        -2.5,           # 11: vertical_rate
        None,           # 12: sensors
        10200.0,        # 13: geo_altitude
        "1000",         # 14: squawk
        False,          # 15: spi
        0,              # 16: position_source
    ]
