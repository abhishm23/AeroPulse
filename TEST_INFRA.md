# AeroPulse: Opaque-Box E2E Test Infrastructure Specification (`TEST_INFRA.md`)

**Document ID**: TEST-INFRA-AEROPULSE-001  
**Author**: E2E Testing Track Lead (`test_writer_e2e`)  
**Date**: 2026-09-05  
**Version**: 1.0.0  
**Status**: ACTIVE & AUTHORITATIVE  

---

## 1. Test Philosophy: Opaque-Box, Requirement-Driven

The AeroPulse E2E Testing Track operates on a strictly **opaque-box, requirement-driven** methodology. Tests are derived directly from the authoritative user specifications documented in `ORIGINAL_REQUEST.md` (Requirements **R1** through **R5** and **Acceptance Criteria**) and interface contracts in `PROJECT.md`.

### 1.1 Core Tenets
1. **Opaque-Box Boundary**: Tests interact solely with the public interfaces of AeroPulse:
   - REST API endpoints (`/api/telemetry`, `/api/flight/{icao24}`, `/api/anomalies`, `/api/stats`, `/api/health`, `/`)
   - Real-time WebSocket protocol (`/ws/telemetry`)
   - Public component contracts (`core.cache.AircraftCache`, `core.anomaly_engine.MechanicalAnomalyEngine`, `core.ingestion.OpenSkyPoller`)
   - Deployment and static asset deliverables (`run.bat`, `static/index.html`, `static/css/hud.css`, `static/js/*.js`)
2. **Zero Facade Tests**: Every test executes real computational logic, validates state transitions, or verifies concrete physical files. No synthetic tautologies (`assert True`) or tests written to mask missing functionality.
3. **Deterministic & Offline Execution**: The test suite requires zero active internet access. High-fidelity OpenSky state vector fixtures and mathematical kinematics simulate realistic airspace conditions deterministically.
4. **Progressive Testability**: During iterative implementation milestones (M1 through M5), the test suite dynamically adapts to available modules. Implemented modules are rigorously tested; unbuilt modules report clean milestone progression signals without failing unrelated test tiers.
5. **Strict SLA Enforcement**: Concrete performance benchmarks enforce the sub-50ms cache retrieval SLA under simulated 1,500 flight loads.

---

## 2. 4-Tier Test Architecture

The E2E test suite is structured into four distinct, escalating tiers of rigor:

```
c:/Projects/AeroPulse/e2e_tests/
├── __init__.py
├── conftest.py               # Shared fixtures, mock feeds, TestClient, test vectors
├── dynamic_loader.py         # Progressive testability & contract compatibility bridge
├── runner.py                 # Tactical CLI unified test runner with JSON reporting
├── test_tier1_features.py    # Tier 1: Feature isolation tests for R1-R5 (>=5 per area)
├── test_tier2_boundaries.py  # Tier 2: Boundary values, dirty data, 429 backoff, SLA (<50ms)
├── test_tier3_pairwise.py    # Tier 3: Combinatorial pairwise cross-feature interactions
└── test_tier4_workloads.py   # Tier 4: Real-world operational scenarios & launcher validation
```

### 2.1 Tier Definitions & Thresholds
- **Tier 1: Feature Isolation (Unit & Contract Verification)**
  - *Threshold*: $\ge 5$ distinct test cases per requirement domain (R1 Ingestion/Cache, R2 Anomaly Traps, R3 HUD Dashboard, R4 Backend API, R5 Verification/Launcher).
  - *Focus*: Happy-path correctness, standard schema validation, component boundary verification.
- **Tier 2: Boundary & Corner Cases (Stress & Resilience)**
  - *Threshold*: $\ge 5$ boundary/corner cases per feature area.
  - *Focus*: Exact mathematical threshold limits (strict vs non-strict inequalities), dirty data injection (`None`, `NaN`, `Inf`, type mismatches), HTTP 429 exponential backoff with jitter, sub-50ms retrieval latency SLA benchmark.
- **Tier 3: Pairwise Cross-Feature Interactions (Combinatorial Integrity)**
  - *Threshold*: Pairwise combinations of core capabilities.
  - *Focus*: Compound anomalies (squawk + descent, squawk + overspeed), concurrent cache reads during TTL pruning, continuous cache serving during HTTP 429 backoff, WebSocket broadcast synchronization on vector ingest.
- **Tier 4: Realistic Workloads & Operational Scenarios (E2E System Validation)**
  - *Threshold*: $\ge 5$ realistic multi-step operational scenarios.
  - *Focus*: Multi-aircraft European airspace simulation, catastrophic decompression flight simulation, consecutive 30-step sparkline trail generation, burst ingestion load test, full static HUD asset inspection, Windows launcher `run.bat` validation.

---

## 3. Feature Inventory & Coverage Matrix

Mapping of all 42 enumerated features from `PROJECT.md` across Tiers 1 through 4:

| Feature ID | Feature Description | Tier 1 | Tier 2 | Tier 3 | Tier 4 | Primary Test Target |
|---|---|:---:|:---:|:---:|:---:|---|
| **F-ING-01** | OpenSky REST API Poller (bounding box 20,-10,60,40) | ✅ | ✅ | — | ✅ | `core.ingestion` query parameters |
| **F-ING-02** | ADS-B Tuple Index Extractor & Robust Sanitizer | ✅ | ✅ | — | — | 17-element ADS-B tuple mapping |
| **F-ING-03** | Sliding-Window Ring Buffer (`deque(maxlen=30)`) | ✅ | — | ✅ | ✅ | Ring buffer history retention |
| **F-ING-04** | HTTP 429 Rate Limit Exponential Backoff & Jitter | ✅ | ✅ | ✅ | — | Backoff delay calculation |
| **F-ING-05** | Network Timeout & Connection Exception Resilience | ✅ | ✅ | — | — | Safe catch of timeout/connection errors |
| **F-ING-06** | Continuous Cache Serving during Ingestion Backoff | — | — | ✅ | ✅ | Cache served during 429 |
| **F-ING-07** | Stale Flight Pruning (120s TTL) | ✅ | — | ✅ | — | Automatic TTL eviction |
| **F-ING-08** | Flight Direction / Heading Recovery | ✅ | — | — | ✅ | True track / azimuth calculation |
| **F-ING-09** | In-Memory Aircraft Snapshot Generation | ✅ | — | — | ✅ | $O(1)$ fast dictionary lookup |
| **F-ING-10** | Synthetic Replay Generator (simulated flights) | — | — | — | ✅ | Deterministic offline mock feed |
| **F-ING-11** | Airborne Flight Filtering (`on_ground == False`) | ✅ | — | ✅ | — | Separation of airborne vs surface |
| **F-ING-12** | Unit Conversion Utilities (m/s to kts, m to ft) | ✅ | ✅ | — | — | Metric to imperial conversions |
| **F-ING-13** | Cache Retrieval Performance Guarantee (<50ms SLA) | — | ✅ | — | ✅ | 1,500 flight latency benchmark |
| **F-ANO-01** | Critical Squawk Trap ("7500", "7600", "7700") | ✅ | ✅ | ✅ | ✅ | Squawk code trigger traps |
| **F-ANO-02** | Severe Descent Vector Trap ($< -20.32\text{ m/s}$) | ✅ | ✅ | ✅ | ✅ | Emergency descent detection |
| **F-ANO-03** | Overspeed Outlier Trap ($> 330\text{ m/s}$ at $< 10,000\text{ m}$) | ✅ | ✅ | ✅ | ✅ | Low-altitude overspeed trap |
| **F-ANO-04** | Human-Readable Rationale String Generation | ✅ | — | ✅ | ✅ | Explicit descriptive rationale |
| **F-ANO-05** | Severity Tier Resolution (CRITICAL, SEVERE, WARNING) | ✅ | — | ✅ | — | AnomalySeverity mapping |
| **F-ANO-06** | Null / NaN / Inf Sensory Immunity | — | ✅ | — | — | Dirty data fault tolerance |
| **F-ANO-07** | Zero False Positives for Nominal Cruise/Climb | ✅ | ✅ | — | ✅ | Baseline nominal flight vectors |
| **F-ANO-08** | Anomaly Event History Buffer & Audit Logging | ✅ | — | ✅ | ✅ | `/api/anomalies` persistence |
| **F-ANO-09** | Multi-Anomaly Compound Flagging | — | — | ✅ | — | Dual/compound triggers |
| **F-ANO-10** | Transponder Loss & Emergency Status Propagation | — | — | ✅ | ✅ | Retained state on signal drop |
| **F-API-01** | FastAPI Application Lifespan (`@asynccontextmanager`) | ✅ | — | — | — | Async lifespan context |
| **F-API-02** | Static File Serving Mount at `/` | ✅ | — | — | ✅ | `GET /` serves HTML |
| **F-API-03** | `GET /api/telemetry` Endpoint | ✅ | — | ✅ | ✅ | Active flight snapshot schema |
| **F-API-04** | `GET /api/flight/{icao24}` Endpoint | ✅ | — | — | ✅ | Single flight detail & history |
| **F-API-05** | `GET /api/anomalies` Endpoint | ✅ | — | ✅ | ✅ | Anomaly audit feed |
| **F-API-06** | `GET /api/stats` Endpoint | ✅ | — | — | ✅ | Aggregate system counters |
| **F-API-07** | `WebSocket /ws/telemetry` Push Endpoint | ✅ | — | ✅ | ✅ | Bi-directional streaming |
| **F-API-08** | `GET /api/health` Endpoint | ✅ | — | — | — | System health diagnostics |
| **F-HUD-01..07**| HUD Layout, Dark Matter Map, CRT Scanlines, Glassmorphism| ✅ | — | — | ✅ | DOM structure, CSS classes, Leaflet |
| **F-HUD-08..11**| Rotating Directional SVG Markers, LERP, Trail Polylines | ✅ | — | — | ✅ | Marker icons, heading, trails |
| **F-HUD-12..17**| Metrics Header, Anomaly Feed, Sortable/Filterable Table | ✅ | — | — | ✅ | UI panel elements in HTML/JS |
| **F-HUD-18..21**| Telemetry Drawer & Canvas Sparklines (Alt/Speed) | ✅ | — | — | ✅ | Drawer DOM, sparkline renderers |
| **F-HUD-22..25**| Web Audio Tactical Radar Ping & Emergency Alarm | ✅ | — | — | ✅ | Audio synthesizer functions |
| **F-HUD-26..29**| WebSocket Client, Polling Fallback, Marker Lifecycle | ✅ | — | — | ✅ | Client network architecture |
| **F-LAUNCH-01** | Windows Launcher `run.bat` (CRLF, kill 8000, start, browser) | ✅ | — | — | ✅ | Batch script validation |

---

## 4. Test Execution Guide

### 4.1 Pytest Execution Commands
```powershell
# Run the complete E2E test suite across all 4 tiers
pytest e2e_tests/ -v

# Run individual tiers
pytest e2e_tests/test_tier1_features.py -v
pytest e2e_tests/test_tier2_boundaries.py -v
pytest e2e_tests/test_tier3_pairwise.py -v
pytest e2e_tests/test_tier4_workloads.py -v

# Run specifically the cache latency SLA benchmark test
pytest e2e_tests/test_tier2_boundaries.py -k "benchmark" -v -s
```

### 4.2 Unified Runner Commands (`e2e_tests/runner.py`)
```powershell
# Run all tiers with tactical HUD terminal output
python -m e2e_tests.runner --all

# Run specific tier
python -m e2e_tests.runner --tier 1
python -m e2e_tests.runner --tier 2
python -m e2e_tests.runner --tier 3
python -m e2e_tests.runner --tier 4

# Export execution report to JSON
python -m e2e_tests.runner --all --json-report e2e_report.json
```

### 4.3 Exit Code Specification
- `0`: All executed tests passed successfully.
- `1`: One or more test assertions failed (implementation defect detected).
- `2`: Severe execution error (invalid arguments or unhandled environment failure).

---

## 5. Authoritative Expected Output Derivations

In accordance with opaque-box testing standards, every test case derives its expected values from documented mathematical formulas and the authoritative user request:

1. **Severe Descent Trap**:
   - Condition: $\text{vertical\_rate} < -20.32\text{ m/s}$ (corresponding to $-4,000\text{ ft/min}$).
   - Test inputs: $-20.320000$ (Nominal), $-20.320001$ (Anomaly), $-30.00$ (Anomaly), $+5.00$ (Nominal).
2. **Overspeed Outlier Trap**:
   - Condition: $\text{velocity} > 330.0\text{ m/s}$ ($> 641.4\text{ kts}$) **AND** $\text{baro\_altitude} < 10,000.0\text{ m}$ ($< 32,808\text{ ft}$).
   - Test inputs: $(330.0, 5000) \to \text{Nominal}$, $(330.1, 5000) \to \text{Anomaly}$, $(350.0, 10000) \to \text{Nominal}$, $(350.0, 9999) \to \text{Anomaly}$.
3. **Squawk Codes**:
   - Condition: $\text{squawk} \in \{"7500", "7600", "7700"\}$.
   - Expected Severity: $7500 \to \text{CRITICAL}$, $7600 \to \text{SEVERE or CRITICAL}$, $7700 \to \text{CRITICAL}$.
4. **Cache Retrieval SLA**:
   - Condition: Retrieval of 1,500 active flights must execute in $p95 < 50.0\text{ ms}$.
