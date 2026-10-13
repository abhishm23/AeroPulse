"""
AeroPulse Telemetry Ingestion Engine
====================================
High-throughput, fault-tolerant ADS-B ingestion worker polling OpenSky Network
REST API with bounds-checked tuple extraction, RFC 8259-compliant sanitization,
full-jitter exponential backoff on HTTP 429, and seamless synthetic replay fallback.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import httpx
from pydantic import BaseModel

from models.aircraft import FlightState

if TYPE_CHECKING:
    from core.cache import AircraftCache
    from core.synthetic import SyntheticReplayGenerator

logger = logging.getLogger("aeropulse.ingestion")

# ============================================================================
# CONSTANTS & CONFIGURATION DEFAULTS
# ============================================================================

OPENSKY_URL = "https://opensky-network.org/api/states/all"
DEFAULT_BBOX: Tuple[float, float, float, float] = (20.0, -10.0, 60.0, 40.0)
DEFAULT_POLL_INTERVAL_MIN: float = 8.0
DEFAULT_POLL_INTERVAL_MAX: float = 10.0
DEFAULT_POLL_INTERVAL: float = 9.0

BACKOFF_BASE_SECONDS: float = 10.0
BACKOFF_MAX_SECONDS: float = 60.0
BACKOFF_JITTER_MIN: float = 0.5
BACKOFF_JITTER_MAX: float = 2.0

DEFAULT_TTL_SECONDS: float = 120.0
SOCKET_TIMEOUT_SECONDS: float = 10.0
SOCKET_CONNECT_TIMEOUT_SECONDS: float = 5.0

# OpenSky ADS-B State Vector 0-Based Indices
INDEX_ICAO24 = 0
INDEX_CALLSIGN = 1
INDEX_ORIGIN_COUNTRY = 2
INDEX_TIME_POSITION = 3
INDEX_LAST_CONTACT = 4
INDEX_LONGITUDE = 5
INDEX_LATITUDE = 6
INDEX_BARO_ALTITUDE = 7
INDEX_ON_GROUND = 8
INDEX_VELOCITY = 9
INDEX_TRUE_TRACK = 10
INDEX_VERTICAL_RATE = 11
INDEX_SENSORS = 12
INDEX_GEO_ALTITUDE = 13
INDEX_SQUAWK = 14
INDEX_SPI = 15
INDEX_POSITION_SOURCE = 16
INDEX_CATEGORY = 17

# Unit Conversion Multipliers
METERS_TO_FEET: float = 3.28084
FEET_TO_METERS: float = 0.3048
MPS_TO_KNOTS: float = 1.943844
KNOTS_TO_MPS: float = 0.514444
MPS_TO_FPM: float = 196.850394
FPM_TO_MPS: float = 0.00508

HEX_PATTERN = re.compile(r"^[0-9a-f]{1,6}$")


# ============================================================================
# ENUMS & DATA MODELS
# ============================================================================

class IngestionMode(str, Enum):
    LIVE_OPENSKY = "LIVE_OPENSKY"
    SYNTHETIC_FALLBACK = "SYNTHETIC_FALLBACK"
    MOCK_REPLAY = "MOCK_REPLAY"
    STOPPED = "STOPPED"


class IngestionDiagnostics(BaseModel):
    """Runtime diagnostics and health metrics for /api/health."""
    mode: IngestionMode = IngestionMode.STOPPED
    is_running: bool = False
    last_poll_timestamp: Optional[float] = None
    last_poll_duration_ms: Optional[float] = None
    total_polls: int = 0
    successful_polls: int = 0
    failed_polls: int = 0
    consecutive_errors: int = 0
    http_429_count: int = 0
    timeout_count: int = 0
    last_error_message: Optional[str] = None
    current_backoff_seconds: float = 0.0
    total_vectors_received: int = 0
    total_vectors_parsed: int = 0
    total_vectors_dropped: int = 0
    active_airborne_count: int = 0


@dataclass
class IngestionCycleResult:
    """Detailed summary of a single poll_once execution for deterministic testing."""
    success: bool
    mode: IngestionMode
    vectors_received: int
    vectors_parsed: int
    vectors_dropped: int
    pruned_count: int
    duration_ms: float
    error_message: Optional[str] = None
    status_code: Optional[int] = None


# ============================================================================
# UNIT CONVERSION HELPERS (F-ING-12)
# ============================================================================

def meters_to_feet(meters: Optional[float]) -> Optional[float]:
    if meters is None:
        return None
    return meters * METERS_TO_FEET


def feet_to_meters(feet: Optional[float]) -> Optional[float]:
    if feet is None:
        return None
    return feet * FEET_TO_METERS


def mps_to_knots(mps: Optional[float]) -> Optional[float]:
    if mps is None:
        return None
    return mps * MPS_TO_KNOTS


def knots_to_mps(knots: Optional[float]) -> Optional[float]:
    if knots is None:
        return None
    return knots * KNOTS_TO_MPS


def mps_to_fpm(mps: Optional[float]) -> Optional[float]:
    if mps is None:
        return None
    return mps * MPS_TO_FPM


def fpm_to_mps(fpm: Optional[float]) -> Optional[float]:
    if fpm is None:
        return None
    return fpm * FPM_TO_MPS


# ============================================================================
# DEFENSIVE SANITIZATION FUNCTIONS (F-ING-02, F-ING-03)
# ============================================================================

def safe_index(row: Any, idx: int, default: Any = None) -> Any:
    """Extract element by index safely without IndexError or null propagation."""
    if isinstance(row, (list, tuple)) and 0 <= idx < len(row):
        val = row[idx]
        return val if val is not None else default
    return default


safe_get = safe_index


def safe_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    """
    Parse float value, strictly rejecting None, NaN, +/-Inf, empty strings,
    and type errors. Guaranteed RFC 8259 JSON compliance.
    """
    if val is None:
        return default
    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            return default
        return float(val)
    if isinstance(val, str):
        cleaned = val.strip()
        if not cleaned or cleaned.lower() in ("nan", "inf", "-inf", "+inf", "null", "none"):
            return default
        try:
            f = float(cleaned)
            if math.isnan(f) or math.isinf(f):
                return default
            return f
        except (ValueError, TypeError):
            return default
    return default


def safe_int(val: Any, default: Optional[int] = None) -> Optional[int]:
    """Safely parse integer value."""
    if val is None:
        return default
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return default
        return int(val)
    if isinstance(val, str):
        cleaned = val.strip()
        try:
            return int(float(cleaned))
        except (ValueError, TypeError):
            return default
    return default


def safe_str(val: Any, default: Optional[str] = None) -> Optional[str]:
    """Safely parse and clean string."""
    if val is None:
        return default
    s = str(val).strip()
    if not s or s.lower() in ("none", "null"):
        return default
    return s


def sanitize_icao24(val: Any) -> Optional[str]:
    """Validate and normalize 24-bit ICAO hex address."""
    s = safe_str(val)
    if not s:
        return None
    cleaned = s.lower()
    if HEX_PATTERN.match(cleaned):
        return cleaned
    return None


def sanitize_callsign(val: Any, icao24: str) -> str:
    """Normalize callsign with uppercase formatting and fallback to ICAO."""
    s = safe_str(val)
    if not s:
        return icao24.upper()
    cleaned = re.sub(r"[^A-Za-z0-9]", "", s).upper()
    return cleaned[:8] if cleaned else icao24.upper()


normalize_callsign = sanitize_callsign


def sanitize_squawk(val: Any) -> Optional[str]:
    """Normalize 4-digit octal transponder squawk code."""
    s = safe_str(val)
    if not s:
        return None
    # Reject if non-digits exist
    if not s.isdigit():
        return None
    padded = s.zfill(4)[-4:]
    # Check octal validity (digits 0-7)
    if all(ch in "01234567" for ch in padded):
        return padded
    return None


normalize_squawk = sanitize_squawk


def validate_lat(val: Optional[float]) -> Optional[float]:
    """Validate latitude within [-90.0, 90.0]."""
    if val is None:
        return None
    return val if -90.0 <= val <= 90.0 else None


def validate_lon(val: Optional[float]) -> Optional[float]:
    """Validate longitude within [-180.0, 180.0]."""
    if val is None:
        return None
    return val if -180.0 <= val <= 180.0 else None


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate forward azimuth (bearing) in degrees [0, 360) between two coordinates."""
    if abs(lat1 - lat2) < 1e-6 and abs(lon1 - lon2) < 1e-6:
        return 0.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)
    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    bearing_rad = math.atan2(y, x)
    bearing_deg = (math.degrees(bearing_rad) + 360.0) % 360.0
    return round(bearing_deg, 1)


def parse_state_vector(
    vector: Any,
    server_time: Optional[float] = None,
    prev_lat: Optional[float] = None,
    prev_lon: Optional[float] = None,
) -> Optional[FlightState]:
    """
    Defensively parse an OpenSky ADS-B state vector row into a FlightState model.
    Returns None if vector is corrupt or missing mandatory icao24.
    """
    if not isinstance(vector, (list, tuple)) or len(vector) < 1:
        return None

    raw_icao = safe_index(vector, INDEX_ICAO24)
    icao24 = sanitize_icao24(raw_icao)
    if not icao24:
        return None

    raw_callsign = safe_index(vector, INDEX_CALLSIGN)
    callsign = sanitize_callsign(raw_callsign, icao24)
    origin_country = safe_str(safe_index(vector, INDEX_ORIGIN_COUNTRY), default="Unknown")

    time_pos = safe_float(safe_index(vector, INDEX_TIME_POSITION))
    contact_time = safe_float(safe_index(vector, INDEX_LAST_CONTACT))
    last_contact = contact_time or time_pos or server_time or time.time()

    lon = validate_lon(safe_float(safe_index(vector, INDEX_LONGITUDE)))
    lat = validate_lat(safe_float(safe_index(vector, INDEX_LATITUDE)))

    baro_altitude = safe_float(safe_index(vector, INDEX_BARO_ALTITUDE))
    geo_altitude = safe_float(safe_index(vector, INDEX_GEO_ALTITUDE))
    on_ground = bool(safe_index(vector, INDEX_ON_GROUND, default=False))

    velocity = safe_float(safe_index(vector, INDEX_VELOCITY))
    vertical_rate = safe_float(safe_index(vector, INDEX_VERTICAL_RATE))

    # True track parsing with heading recovery
    raw_track = safe_float(safe_index(vector, INDEX_TRUE_TRACK))
    if raw_track is not None:
        true_track = round(raw_track % 360.0, 1)
    elif lat is not None and lon is not None and prev_lat is not None and prev_lon is not None:
        true_track = calculate_bearing(prev_lat, prev_lon, lat, lon)
    else:
        true_track = None

    squawk = sanitize_squawk(safe_index(vector, INDEX_SQUAWK))

    try:
        return FlightState(
            icao24=icao24,
            callsign=callsign,
            origin_country=origin_country,
            longitude=lon,
            latitude=lat,
            baro_altitude=baro_altitude,
            velocity=velocity,
            vertical_rate=vertical_rate,
            squawk=squawk,
            true_track=true_track,
            on_ground=on_ground,
            last_contact=last_contact,
            geo_altitude=geo_altitude,
        )
    except Exception as exc:
        logger.debug("Failed constructing FlightState: %s", exc)
        return None


sanitize_tuple = parse_state_vector


# ============================================================================
# OPENSKY INGESTION WORKER CLASS
# ============================================================================

class OpenSkyIngestionWorker:
    """
    Asynchronous telemetry ingestion worker with full jitter exponential backoff,
    defensive tuple parsing, seamless synthetic fallback, and cache management.
    """

    def __init__(
        self,
        cache: Any,
        synthetic_generator: Optional[Any] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        bounding_box: Tuple[float, float, float, float] = DEFAULT_BBOX,
        force_mock: bool = False,
        fallback_enabled: bool = True,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        client: Optional[httpx.AsyncClient] = None,
        user_agent: str = "AeroPulse/1.0 (Military-HUD-Telemetry-Engine)",
    ):
        self.cache = cache
        self.synthetic_generator = synthetic_generator
        self.poll_interval = poll_interval
        self.bounding_box = bounding_box
        self.force_mock = force_mock
        self.fallback_enabled = fallback_enabled
        self.ttl_seconds = ttl_seconds
        self._user_agent = user_agent

        # HTTP Client management
        self._external_client = client is not None
        self._client = client

        # Worker state & task handle
        self._task: Optional[asyncio.Task] = None
        self._is_running: bool = False
        self._shutdown_event = asyncio.Event()

        # Diagnostics & Error tracking
        self.diagnostics = IngestionDiagnostics(
            mode=IngestionMode.MOCK_REPLAY if force_mock else IngestionMode.STOPPED
        )

    # ------------------------------------------------------------------------
    # Client & Resource Lifecycle
    # ------------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or initialize the httpx.AsyncClient with appropriate timeouts."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    SOCKET_TIMEOUT_SECONDS,
                    connect=SOCKET_CONNECT_TIMEOUT_SECONDS,
                ),
                headers={"User-Agent": self._user_agent},
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._client

    async def close(self) -> None:
        """Close underlying HTTP client resources."""
        if self._client is not None and not self._client.is_closed and not self._external_client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------------
    # Backoff & Full Jitter Calculations
    # ------------------------------------------------------------------------

    def _calculate_backoff(self) -> float:
        """
        Calculate exponential backoff with full jitter:
        temp = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * 2^consecutive_errors)
        backoff = uniform(BACKOFF_BASE_SECONDS, temp) + uniform(JITTER_MIN, JITTER_MAX)
        """
        errors = max(1, self.diagnostics.consecutive_errors)
        temp = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * (2 ** min(errors, 6)))
        jitter = random.uniform(BACKOFF_JITTER_MIN, BACKOFF_JITTER_MAX)
        backoff = random.uniform(BACKOFF_BASE_SECONDS, temp) + jitter
        self.diagnostics.current_backoff_seconds = round(backoff, 2)
        return backoff

    # ------------------------------------------------------------------------
    # OpenSky Network Fetcher
    # ------------------------------------------------------------------------

    async def _fetch_opensky(self) -> Tuple[int, Optional[Dict[str, Any]]]:
        """
        Execute HTTP GET against OpenSky REST API with bounding box query params.
        Returns (status_code, parsed_json_dict).
        """
        client = await self._get_client()
        lamin, lomin, lamax, lomax = self.bounding_box
        params = {
            "lamin": lamin,
            "lomin": lomin,
            "lamax": lamax,
            "lomax": lomax,
        }

        response = await client.get(OPENSKY_URL, params=params)
        status_code = response.status_code

        if status_code == 200:
            try:
                data = response.json()
                return status_code, data
            except Exception as json_err:
                logger.warning("OpenSky returned HTTP 200 with invalid JSON: %s", json_err)
                return 500, None

        return status_code, None

    # ------------------------------------------------------------------------
    # Synthetic Fallback Handler
    # ------------------------------------------------------------------------

    def _ensure_synthetic_generator(self) -> Any:
        """Lazily initialize synthetic generator if not injected."""
        if self.synthetic_generator is None:
            try:
                from core.synthetic import SyntheticReplayGenerator
                self.synthetic_generator = SyntheticReplayGenerator()
            except ImportError:
                logger.error("SyntheticReplayGenerator could not be imported from core.synthetic")
        return self.synthetic_generator

    def _generate_synthetic_states(self) -> List[FlightState]:
        """Generate a kinematic step from the synthetic generator."""
        generator = self._ensure_synthetic_generator()
        if generator is not None:
            return generator.tick()
        return []

    # ------------------------------------------------------------------------
    # Single Poll Execution (poll_once)
    # ------------------------------------------------------------------------

    async def poll_once(self) -> IngestionCycleResult:
        """
        Execute a single ingestion cycle:
        1. Query OpenSky (or delegate to synthetic generator).
        2. Defensively parse and sanitize state vectors.
        3. Ingest into cache and prune stale vectors.
        4. Update diagnostics and return detailed cycle result.
        """
        start_time = time.perf_counter()
        self.diagnostics.total_polls += 1
        self.diagnostics.last_poll_timestamp = time.time()

        # CASE 1: Forced Mock / Offline Replay Mode
        if self.force_mock:
            self.diagnostics.mode = IngestionMode.MOCK_REPLAY
            states = self._generate_synthetic_states()
            parsed_count = 0
            for state in states:
                self.cache.update_vector(state)
                parsed_count += 1

            pruned = self.cache.prune_stale(self.ttl_seconds)
            duration_ms = (time.perf_counter() - start_time) * 1000.0

            self.diagnostics.successful_polls += 1
            self.diagnostics.consecutive_errors = 0
            self.diagnostics.total_vectors_received += len(states)
            self.diagnostics.total_vectors_parsed += parsed_count
            self.diagnostics.last_poll_duration_ms = round(duration_ms, 2)

            return IngestionCycleResult(
                success=True,
                mode=IngestionMode.MOCK_REPLAY,
                vectors_received=len(states),
                vectors_parsed=parsed_count,
                vectors_dropped=0,
                pruned_count=pruned,
                duration_ms=duration_ms,
                status_code=200,
            )

        # CASE 2: Live Polling Attempt
        status_code: Optional[int] = None
        error_msg: Optional[str] = None
        raw_states: Optional[List[Any]] = None

        try:
            status_code, data = await self._fetch_opensky()
            if status_code == 200 and data is not None:
                # Handle {"states": null}
                raw_states = data.get("states") or []
            elif status_code == 429:
                self.diagnostics.http_429_count += 1
                error_msg = "HTTP 429 Too Many Requests: Rate limit exceeded"
                logger.warning("OpenSky rate limit hit (HTTP 429).")
            else:
                error_msg = f"HTTP {status_code} error from OpenSky"
                logger.warning("OpenSky returned HTTP status: %s", status_code)

        except (httpx.TimeoutException, asyncio.TimeoutError) as timeout_exc:
            self.diagnostics.timeout_count += 1
            error_msg = f"Network timeout communicating with OpenSky: {timeout_exc}"
            logger.warning(error_msg)
        except (httpx.ConnectError, httpx.NetworkError) as conn_exc:
            error_msg = f"Connection failure communicating with OpenSky: {conn_exc}"
            logger.warning(error_msg)
        except Exception as general_exc:
            error_msg = f"Unexpected error querying OpenSky: {general_exc}"
            logger.error(error_msg, exc_info=True)

        # CASE 2A: Upstream Succeeded (Live OpenSky)
        if status_code == 200 and raw_states is not None:
            self.diagnostics.mode = IngestionMode.LIVE_OPENSKY
            self.diagnostics.successful_polls += 1
            self.diagnostics.consecutive_errors = 0
            self.diagnostics.current_backoff_seconds = 0.0

            vectors_received = len(raw_states)
            self.diagnostics.total_vectors_received += vectors_received

            parsed_count = 0
            dropped_count = 0

            for row in raw_states:
                try:
                    icao = safe_index(row, INDEX_ICAO24)
                    prev_lat, prev_lon = None, None
                    if icao:
                        existing = self.cache.get_flight(str(icao).strip().lower())
                        if existing and existing.latitude is not None and existing.longitude is not None:
                            prev_lat, prev_lon = existing.latitude, existing.longitude

                    flight_state = parse_state_vector(row, prev_lat=prev_lat, prev_lon=prev_lon)
                    if flight_state:
                        self.cache.update_vector(flight_state)
                        parsed_count += 1
                    else:
                        dropped_count += 1
                except Exception as parse_exc:
                    logger.debug("Failed parsing row %s: %s", row, parse_exc)
                    dropped_count += 1

            pruned = self.cache.prune_stale(self.ttl_seconds)
            duration_ms = (time.perf_counter() - start_time) * 1000.0

            self.diagnostics.total_vectors_parsed += parsed_count
            self.diagnostics.total_vectors_dropped += dropped_count
            self.diagnostics.last_poll_duration_ms = round(duration_ms, 2)

            return IngestionCycleResult(
                success=True,
                mode=IngestionMode.LIVE_OPENSKY,
                vectors_received=vectors_received,
                vectors_parsed=parsed_count,
                vectors_dropped=dropped_count,
                pruned_count=pruned,
                duration_ms=duration_ms,
                status_code=200,
            )

        # CASE 2B: Upstream Failed -> Delegate to Synthetic Fallback
        self.diagnostics.failed_polls += 1
        self.diagnostics.consecutive_errors += 1
        self.diagnostics.last_error_message = error_msg

        fallback_parsed = 0
        pruned = 0
        mode = IngestionMode.SYNTHETIC_FALLBACK

        if self.fallback_enabled:
            self.diagnostics.mode = IngestionMode.SYNTHETIC_FALLBACK
            logger.info("Delegating to SyntheticReplayGenerator during OpenSky outage...")
            states = self._generate_synthetic_states()
            for state in states:
                self.cache.update_vector(state)
                fallback_parsed += 1
            pruned = self.cache.prune_stale(self.ttl_seconds)
            self.diagnostics.total_vectors_parsed += fallback_parsed

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        self.diagnostics.last_poll_duration_ms = round(duration_ms, 2)

        return IngestionCycleResult(
            success=False,
            mode=mode,
            vectors_received=0,
            vectors_parsed=fallback_parsed,
            vectors_dropped=0,
            pruned_count=pruned,
            duration_ms=duration_ms,
            error_message=error_msg,
            status_code=status_code,
        )

    # ------------------------------------------------------------------------
    # Background Task Lifecycle (run_loop, start, stop)
    # ------------------------------------------------------------------------

    async def run_loop(self) -> None:
        """Continuous background polling loop with backoff and cancellation handling."""
        self._is_running = True
        self.diagnostics.is_running = True
        logger.info("OpenSkyIngestionWorker background loop started.")

        try:
            while self._is_running and not self._shutdown_event.is_set():
                result = await self.poll_once()

                if not result.success:
                    sleep_time = self._calculate_backoff()
                    logger.warning(
                        "Upstream poll failed (%s). Backing off for %.2fs with full jitter...",
                        result.error_message,
                        sleep_time,
                    )
                else:
                    sleep_time = random.uniform(
                        DEFAULT_POLL_INTERVAL_MIN,
                        DEFAULT_POLL_INTERVAL_MAX,
                    )

                # Cooperative cancellable sleep
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=sleep_time)
                    break  # Shutdown event was set
                except asyncio.TimeoutError:
                    continue  # Timeout expired normally, execute next cycle

        except asyncio.CancelledError:
            logger.info("OpenSkyIngestionWorker loop received cancellation signal.")
        finally:
            self._is_running = False
            self.diagnostics.is_running = False
            self.diagnostics.mode = IngestionMode.STOPPED
            await self.close()
            logger.info("OpenSkyIngestionWorker background loop terminated.")

    def start(self) -> asyncio.Task:
        """Launch the worker in an asynchronous background task."""
        if self._task is None or self._task.done():
            self._shutdown_event.clear()
            self._task = asyncio.create_task(self.run_loop(), name="opensky_ingestion_worker")
        return self._task

    async def stop(self) -> None:
        """Gracefully request shutdown, await task completion, and clean up resources."""
        self._is_running = False
        self._shutdown_event.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.close()

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return diagnostic metrics dictionary for /api/health."""
        return self.diagnostics.model_dump()


# Class Aliases for Dynamic Loaders and Framework Integration
IngestionWorker = OpenSkyIngestionWorker
OpenSkyPoller = OpenSkyIngestionWorker
