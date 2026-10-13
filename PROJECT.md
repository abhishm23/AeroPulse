# Project: AeroPulse

## Architecture
AeroPulse is a high-throughput, mechanical flight anomaly detection engine paired with a premium military/tactical HUD-style dark-mode dashboard.

### Core Principles
1. **Deterministic Kinematics**: Zero ML, zero LLMs. Mathematical thresholding for anomaly detection traps.
2. **Resilient Ingestion**: Asynchronous background polling of OpenSky Network REST API with sliding ring-buffer caching, exponential backoff with jitter on HTTP 429 rate limits, and an integrated deterministic synthetic replay generator for 100% offline reliability.
3. **High-Performance In-Memory Cache**: Thread-safe in-memory caching keyed by ICAO24 with sliding window `deque(maxlen=30)` for instantaneous $O(1)$ lookups and $<50\text{ms}$ (typically $<3\text{ms}$) snapshot serialization.
4. **FastAPI Backend & WebSocket Push**: REST endpoints (`/api/telemetry`, `/api/flight/{icao24}`, `/api/anomalies`, `/api/stats`, `/api/health`) and real-time WebSocket push (`/ws/telemetry`), serving static assets at `/`.
5. **Tactical Military HUD Frontend**: Vanilla JavaScript (modular ES6) and CSS3 rendered via Leaflet.js with CartoDB Dark Matter tiles. Glowing neon accents (cyan/green nominal, pulsing crimson anomalous), CRT scanline overlays, rotating directional SVG aircraft markers, 60 FPS smooth coordinate/heading LERP, HTML5 canvas sparklines, and synthesized Web Audio alerts.
6. **Zero-Network Verification**: Automated pytest suite verifying boundary thresholds, tuple sanitization against dirty data (None/NaN/Inf), API contract validation, and $<50\text{ms}$ cache retrieval SLA.

### System Data Flow
```
OpenSky Network REST API (or Synthetic Replay)
                   │
                   ▼ (Every 8-10s / async worker)
     [OpenSkyPoller / Sanitizer]
                   │
                   ▼ (Sanitized AircraftState)
         [SlidingRingBufferCache] ◄── Prunes stale flights (>120s TTL)
                   │
                   ▼ (On vector update)
     [MechanicalAnomalyEngine] ──► Flags: 7500/7600/7700, Descent < -20.32m/s, Speed > 330m/s
                   │
                   ├───────────────────────────────┐
                   ▼                               ▼
       [FastAPI REST API Routes]          [WebSocket Broadcaster]
   /api/telemetry, /api/flight/{icao24}        /ws/telemetry
   /api/anomalies, /api/stats, /api/health         │
                   │                               │
                   └───────────────┬───────────────┘
                                   ▼
                   [Military HUD Dashboard (Leaflet)]
                   - CartoDB Dark Matter Tiles
                   - Directional SVG Flight Icons (LERP animated)
                   - Pulsing Crimson Anomalies / Cyan Nominal
                   - Flight Trail Polylines
                   - Telemetry Drawer + Canvas Sparklines
                   - Sortable/Filterable Data Table
                   - Web Audio Tactical Alerts
```

---

## Feature Inventory
Every feature from the Survey phase is mapped to an authoritative milestone:

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | `F-ING-01` | OpenSky REST API Poller (HTTP GET bounding box lamin=20, lomin=-10, lamax=60, lomax=40 at 8-10s cadence) | M1 | survey |
| 2 | `F-ING-02` | ADS-B Tuple Index Extractor & Robust Sanitizer (safe float parsing, null/None/NaN/Inf protection) | M1 | survey |
| 3 | `F-ING-03` | Sliding-Window Ring Buffer Cache (`deque(maxlen=30)` per aircraft keyed by ICAO24) | M1 | survey |
| 4 | `F-ING-04` | HTTP 429 Rate Limit Handling with Exponential Backoff & Jitter | M1 | survey |
| 5 | `F-ING-05` | Network Timeout & Connection Exception Resilience | M1 | survey |
| 6 | `F-ING-06` | Continuous Cache Serving during Ingestion Outages / Backoff | M1 | survey |
| 7 | `F-ING-07` | Stale Flight Pruning (120s TTL) | M1 | survey |
| 8 | `F-ING-08` | Flight Direction / Heading Recovery (true_track or forward azimuth calculation) | M1 | survey |
| 9 | `F-ING-09` | In-Memory Aircraft Snapshot Generation (O(1) lookups, sub-millisecond retrieval) | M1 | survey |
| 10 | `F-ING-10` | Synthetic Replay Generator (30-50 realistic simulated European flights with scripted anomalies) | M1 | survey |
| 11 | `F-ING-11` | Airborne Flight Filtering (`on_ground == False`) | M1 | survey |
| 12 | `F-ING-12` | Unit Conversion Utilities (m/s to kts, m to ft, m/s to ft/min) | M1 | survey |
| 13 | `F-ING-13` | Cache Retrieval Performance Guarantee (<50ms SLA) | M1 | survey |
| 14 | `F-ANO-01` | Critical Squawk Trap ("7500" Hijack, "7600" Radio Failure, "7700" Emergency) | M2 | survey |
| 15 | `F-ANO-02` | Severe Descent Vector Trap (vertical_rate < -20.32 m/s / -4000 ft/min) | M2 | survey |
| 16 | `F-ANO-03` | Overspeed Outlier Trap (velocity > 330.0 m/s / > 640 kts at baro_altitude < 10,000 m) | M2 | survey |
| 17 | `F-ANO-04` | Human-Readable Rationale String Generation | M2 | survey |
| 18 | `F-ANO-05` | Severity Tier Resolution (CRITICAL, SEVERE, WARNING, NOMINAL) | M2 | survey |
| 19 | `F-ANO-06` | Null / NaN / Inf Sensory Immunity (Zero unhandled exceptions) | M2 | survey |
| 20 | `F-ANO-07` | Zero False Positives for Nominal Cruise/Climb/Approach | M2 | survey |
| 21 | `F-ANO-08` | Anomaly Event History Buffer & Audit Logging (retaining recent anomaly events with timestamps) | M2 | survey |
| 22 | `F-ANO-09` | Multi-Anomaly Compound Flagging | M2 | survey |
| 23 | `F-ANO-10` | Transponder Loss & Emergency Status Propagation | M2 | survey |
| 24 | `F-API-01` | FastAPI Application Lifespan & Lifecycle Management (`@asynccontextmanager`) | M3 | survey |
| 25 | `F-API-02` | Static File Serving Mount at `/` (`index.html`, CSS, JS, audio) | M3 | survey |
| 26 | `F-API-03` | `GET /api/telemetry` Endpoint (active vectors, kinematic params, anomaly flags, trails) | M3 | survey |
| 27 | `F-API-04` | `GET /api/flight/{icao24}` Endpoint (detailed kinematic history for specific flight) | M3 | survey |
| 28 | `F-API-05` | `GET /api/anomalies` Endpoint (recent anomaly events log with timestamps and severity) | M3 | survey |
| 29 | `F-API-06` | `GET /api/stats` Endpoint (aggregate statistics, anomalies per category, uptime, cache health) | M3 | survey |
| 30 | `F-API-07` | `WebSocket /ws/telemetry` Endpoint (ConnectionManager, snapshot push, broadcast updates) | M3 | survey |
| 31 | `F-API-08` | `GET /api/health` Endpoint (system health, mode, cache stats) | M3 | survey |
| 32 | `F-HUD-01` | Single-Page Full-Viewport Map Container | M4 | survey |
| 33 | `F-HUD-02` | CartoDB Dark Matter Leaflet Tile Layer Integration | M4 | survey |
| 34 | `F-HUD-03` | Military/Tactical Color Palette & Styling System | M4 | survey |
| 35 | `F-HUD-04` | Tactical CRT Scanline & Screen Vignette Overlay | M4 | survey |
| 36 | `F-HUD-05` | Animated Radar Sweep Visual Effect | M4 | survey |
| 37 | `F-HUD-06` | Monospaced Typography System (JetBrains Mono / Share Tech Mono via CDN/webfont) | M4 | survey |
| 38 | `F-HUD-07` | Glassmorphism Floating Overlay Panels (backdrop-filter: blur, border glow) | M4 | survey |
| 39 | `F-HUD-08` | Animated Directional SVG Aircraft Markers (rotating to aircraft heading) | M4 | survey |
| 40 | `F-HUD-09` | Status-Based Neon Marker Encoding (Cyan/Green nominal, Pulsing Red/Crimson anomalous) | M4 | survey |
| 41 | `F-HUD-10` | Smooth Kinematic Marker Interpolation (60 FPS LERP & shortest-arc heading rotation) | M4 | survey |
| 42 | `F-HUD-11` | Live Flight Path Trail Lines (rendered from ring buffer) | M4 | survey |
| 43 | `F-HUD-12` | Top Header Metrics Bar (airborne count, anomaly tally, status, live UTC clock) | M4 | survey |
| 44 | `F-HUD-13` | Anomaly Event Feed Panel (scrollable feed, severity badges, timestamp, callsign) | M4 | survey |
| 45 | `F-HUD-14` | Focus Aircraft on Map from Anomaly Feed Click | M4 | survey |
| 46 | `F-HUD-15` | Toggleable Aircraft Data Table Overlay | M4 | survey |
| 47 | `F-HUD-16` | Sortable Aircraft Data Table Columns (Callsign, Alt, Speed, Status) | M4 | survey |
| 48 | `F-HUD-17` | Filterable Aircraft Data Table (Search by Callsign / Status) | M4 | survey |
| 49 | `F-HUD-18` | Interactive Telemetry Drawer (slides out on aircraft click) | M4 | survey |
| 50 | `F-HUD-19` | Telemetry Detail Fields (Callsign, ICAO, Country, Speed, Alt, Climb Rate, Squawk, Rationale) | M4 | survey |
| 51 | `F-HUD-20` | Mini-Chart HTML5 Canvas Altitude Sparkline | M4 | survey |
| 52 | `F-HUD-21` | Mini-Chart HTML5 Canvas Speed Sparkline | M4 | survey |
| 53 | `F-HUD-22` | Web Audio API Tactical Radar Ping for Nominal/New Detection | M4 | survey |
| 54 | `F-HUD-23` | Web Audio API Emergency Klaxon / Alarm for Critical Anomaly | M4 | survey |
| 55 | `F-HUD-24` | Audio Toggle / Mute Control with State Persistence | M4 | survey |
| 56 | `F-HUD-25` | Browser Audio Autoplay Unlock on First Interaction | M4 | survey |
| 57 | `F-HUD-26` | WebSocket Live Telemetry Client (`/ws/telemetry`) | M4 | survey |
| 58 | `F-HUD-27` | Automatic Polling Fallback (`/api/telemetry` every 3-5s if WS drops) | M4 | survey |
| 59 | `F-HUD-28` | WebSocket Exponential Backoff Reconnection | M4 | survey |
| 60 | `F-HUD-29` | Stale Marker Cleanup & Leaflet Object Lifecycle Management | M4 | survey |
| 61 | `F-HUD-30` | Responsive Viewport Layout (Desktop & Tablet adaptation) | M4 | survey |
| 62 | `F-HUD-31` | Zero Console JavaScript Errors | M4 | survey |
| 63 | `F-HUD-32` | Visual Ingestion Mode Indicator (LIVE OPENSKY vs MOCK REPLAY) | M4 | survey |
| 64 | `F-TEST-01` | Deterministic Anomaly Traps Unit Tests (boundary values & edge cases) | M5 | survey |
| 65 | `F-TEST-02` | ADS-B Tuple Parsing & Null/None/NaN Resilience Tests | M5 | survey |
| 66 | `F-TEST-03` | API Contract Tests for all 6 REST/WS endpoints via TestClient | M5 | survey |
| 67 | `F-TEST-04` | Cache Performance Benchmark Test (< 50ms retrieval SLA) | M5 | survey |
| 68 | `F-TEST-05` | Deterministic Mock / Replay Fixture Harness for Offline Testing | M5 | survey |
| 69 | `F-LAUNCH-01` | Windows Launcher `run.bat` (CRLF line endings, port 8000 clearance, uvicorn start, browser launch) | M5 | survey |

---

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Ingestion & Resilient Caching | `core/ingestion.py`, `core/cache.py`, `models/aircraft.py`, `core/synthetic.py` (Features F-ING-01..13) | none | PLANNED |
| M2 | Deterministic Anomaly Engine | `core/anomaly_engine.py`, `models/anomaly.py` (Features F-ANO-01..10) | M1 | PLANNED |
| M3 | Backend REST & WebSocket Services | `main.py`, `api/routes.py`, `api/websocket.py`, `models/schemas.py` (Features F-API-01..08) | M1, M2 | PLANNED |
| M4 | Military HUD Dashboard | `static/index.html`, `static/css/*`, `static/js/*` (Features F-HUD-01..32) | M3 | PLANNED |
| M5 | Automated Verification Suite & Launcher | `tests/*`, `run.bat`, `requirements.txt` (Features F-TEST-01..05, F-LAUNCH-01) | M1, M2, M3 | PLANNED |
| E2E | Requirement-Driven Opaque-Box E2E Testing Track | `e2e_tests/*`, `TEST_INFRA.md`, `TEST_READY.md` (Tiers 1-4 independent tests) | none (parallel track) | PLANNED |
| Final | Final E2E Pass & Adversarial Coverage Hardening | Phase 1 (100% E2E Pass Tiers 1-4) + Phase 2 (Tier 5 Challenger Hardening + Forensic Audit) | M4, M5, E2E | PLANNED |

---

## Interface Contracts

### `core/cache.py` ↔ `core/ingestion.py`
```python
class FlightState(BaseModel):
    icao24: str
    callsign: Optional[str]
    origin_country: Optional[str]
    longitude: Optional[float]
    latitude: Optional[float]
    baro_altitude: Optional[float]  # meters
    velocity: Optional[float]       # m/s
    vertical_rate: Optional[float]  # m/s
    squawk: Optional[str]
    true_track: Optional[float]     # degrees [0, 360)
    last_contact: float             # epoch seconds

class AircraftCache:
    def update_vector(self, state: FlightState) -> None: ...
    def get_all_active(self) -> List[AircraftDetail]: ...
    def get_flight(self, icao24: str) -> Optional[AircraftDetail]: ...
    def prune_stale(self, ttl_seconds: float = 120.0) -> int: ...
    def get_stats(self) -> Dict[str, Any]: ...
```

### `core/anomaly_engine.py` ↔ `core/cache.py` / `api/routes.py`
```python
class AnomalySeverity(str, Enum):
    NOMINAL = "NOMINAL"
    WARNING = "WARNING"
    SEVERE = "SEVERE"
    CRITICAL = "CRITICAL"

class AnomalyFlag(BaseModel):
    category: str        # SQUAWK_EMERGENCY, SEVERE_DESCENT, OVERSPEED
    severity: AnomalySeverity
    rationale: str
    timestamp: float

class MechanicalAnomalyEngine:
    @staticmethod
    def evaluate(state: FlightState) -> List[AnomalyFlag]: ...
    @staticmethod
    def resolve_severity(flags: List[AnomalyFlag]) -> AnomalySeverity: ...
```

### `api/routes.py` & `api/websocket.py` ↔ Frontend `static/js/network.js`
- `GET /api/telemetry` -> `{ "count": int, "airborne": int, "anomalies": int, "timestamp": float, "flights": [AircraftDetail] }`
- `GET /api/flight/{icao24}` -> `AircraftDetail` (with `history`: list of trail coordinates, altitude, velocity)
- `GET /api/anomalies` -> `[ { "id": str, "icao24": str, "callsign": str, "category": str, "severity": str, "rationale": str, "timestamp": float } ]`
- `GET /api/stats` -> `{ "total_tracked": int, "active_count": int, "anomaly_counts": dict, "cache_size": int, "uptime_seconds": float }`
- `WebSocket /ws/telemetry` -> Initial `type: "SNAPSHOT"`, periodic `type: "UPDATE"`, `type: "PONG"`

---

## Code Layout
```
c:/Projects/AeroPulse/
├── core/
│   ├── __init__.py
│   ├── ingestion.py          # OpenSky async polling worker with backoff & retry
│   ├── cache.py              # Ring-buffer sliding cache, thread-safe, TTL pruning
│   ├── anomaly_engine.py     # Pure deterministic mathematical threshold traps
│   └── synthetic.py          # Deterministic simulated European flights for offline/dev
├── models/
│   ├── __init__.py
│   ├── aircraft.py           # FlightState, TrailPoint, AircraftDetail Pydantic models
│   ├── anomaly.py            # AnomalyFlag, AnomalySeverity, AnomalyRecord
│   └── schemas.py            # API response schemas for REST endpoints
├── api/
│   ├── __init__.py
│   ├── routes.py             # 5 REST endpoints (/api/telemetry, flight, anomalies, stats, health)
│   └── websocket.py          # WebSocket /ws/telemetry push connection manager
├── static/
│   ├── index.html            # Single-page full-viewport HUD dark-mode layout
│   ├── css/
│   │   ├── hud.css           # Military HUD styling, CRT scanlines, glassmorphism, radar sweep
│   │   └── leaflet.css       # Leaflet 1.9.4 styles (CDN or local)
│   └── js/
│       ├── app.js            # Main HUD coordinator, state initialization
│       ├── map.js            # Leaflet CartoDB Dark Matter map setup & view management
│       ├── markers.js        # Directional rotating SVG markers, 60fps LERP interpolation
│       ├── trails.js         # Flight trail polyline rendering from ring buffer
│       ├── panels.js         # Header metrics, anomaly feed, interactive telemetry drawer, data table
│       ├── sparklines.js     # Pure HTML5 Canvas altitude & speed trend charts
│       ├── audio.js          # Web Audio API radar pings and emergency alarms
│       └── network.js        # Dual-mode WebSocket client with HTTP auto-polling fallback
├── tests/
│   ├── conftest.py           # Pytest fixtures and mock client
│   ├── test_anomaly_traps.py # Boundary tests for squawk, descent, overspeed, nominal zero-false-positive
│   ├── test_tuple_parsing.py # Null/None/NaN/Inf/missing field robustness tests
│   ├── test_api_contracts.py # TestClient endpoint schema & response status tests
│   ├── test_cache_benchmark.py # Sub-50ms cache retrieval SLA benchmark test
│   └── fixtures/
│       ├── sample_states.json # Realistic OpenSky vector sample
│       └── anomaly_cases.json # Verified anomaly vector fixtures
├── e2e_tests/
│   ├── test_runner.py        # Independent requirement-driven opaque-box test runner
│   ├── tier1_features.py     # Tier 1: Feature coverage (>=5 tests per feature)
│   ├── tier2_boundaries.py   # Tier 2: Boundary & corner cases (>=5 per feature)
│   ├── tier3_pairwise.py     # Tier 3: Combinatorial feature interactions
│   └── tier4_workloads.py    # Tier 4: Real-world operational scenarios
├── main.py                   # FastAPI app entry point, lifespan, static mounting
├── requirements.txt          # fastapi, uvicorn, httpx, pydantic, pytest, pytest-asyncio, websockets
├── run.bat                   # Windows batch launcher (CRLF line endings, port 8000 kill, start server, open browser)
├── ORIGINAL_REQUEST.md       # Verbatim user requirements
├── PROJECT.md                # This project roadmap and architecture index
├── TEST_INFRA.md             # E2E test track methodology and feature matrix
└── TEST_READY.md             # E2E test suite publish signal
```
