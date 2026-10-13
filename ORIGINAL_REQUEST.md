# Original User Request

## Initial Request — 2026-09-05T15:21:39Z

Rebuild AeroPulse from scratch as a polished showcase demo: a high-throughput, mechanical flight anomaly detection engine with a premium military/tactical HUD-style dark-mode dashboard. Pure Python backend (FastAPI, Python 3.11+), vanilla JS/CSS/Leaflet frontend (no React, Vue, or heavy frameworks). Deterministic mathematical thresholding for anomaly detection — zero ML, zero LLMs. The working directory must be wiped clean before starting. Quality bar: visually stunning, functionally complete, demo-ready.

Working directory: c:/Projects/AeroPulse
Integrity mode: development

**IMPORTANT: Delete all existing files in the working directory before starting. This is a clean-slate rebuild.**

## Requirements

### R1. Real-Time ADS-B Ingestion & Resilient Caching
- Async background worker continuously polling OpenSky Network REST API (`https://opensky-network.org/api/states/all`) with bounded geographical box (`lamin=20&lomin=-10&lamax=60&lomax=40`) at 8–10 second cadence.
- Parse raw ADS-B state vector tuple indices: `[0]` ICAO24, `[1]` Callsign, `[2]` Origin Country, `[5]` Longitude, `[6]` Latitude, `[7]` Barometric Altitude, `[9]` Velocity, `[11]` Vertical Rate, `[14]` Squawk.
- In-memory sliding-window ring buffer per aircraft (keyed by ICAO24) retaining recent kinematic history for trail rendering and trend analysis.
- Graceful handling of OpenSky unauthenticated rate limits (HTTP 429) and network timeouts via exponential backoff, continuously serving cached states without interruption.

### R2. Deterministic Mechanical Anomaly Detection Engine
- Zero-ML mathematical kinematic threshold traps:
  - **Critical Squawk Trap:** Flag squawk codes `"7500"` (Unlawful Interference/Hijack), `"7600"` (Radio Communication Failure), `"7700"` (General Emergency).
  - **Severe Descent Vector:** Flag vertical rate < -20.32 m/s (-4,000 ft/min) indicating emergency depressurization descent.
  - **Overspeed Outlier:** Flag velocity > 330 m/s (> 640 knots) at altitude < 10,000 m.
- Each anomaly carries a human-readable rationale string and severity level (CRITICAL, SEVERE, WARNING).
- Robust against null, None, NaN, Inf, and missing sensor fields in ADS-B tuples — no unhandled exceptions.

### R3. Premium Military/Tactical HUD Dark-Mode Dashboard
The dashboard must be a single-page, full-viewport, dark-mode web application rendered with Leaflet.js (CartoDB Dark Matter tiles) and vanilla JavaScript/CSS. No heavy frontend frameworks (React, Vue, Angular). The visual style must be **military/tactical HUD**: glowing neon accents (cyan, green, amber, crimson), scanline/CRT overlay effects, radar sweep animations, monospaced fonts (e.g., JetBrains Mono, Share Tech Mono), and glass-morphism floating panels.

Specific interactive features required:
- **Full-viewport map** with CartoDB Dark Matter tiles as the base layer.
- **Floating glass-morphism overlay panels** for metrics, alerts, and telemetry (not traditional sidebars).
- **Animated directional flight icons** showing aircraft heading instead of plain circle markers.
- **Live aircraft trail lines** (flight path history rendered on map from ring buffer data).
- **Smooth animated marker movement** — aircraft positions interpolate smoothly between updates instead of jumping.
- **Real-time auto-updating telemetry** — dashboard polls the backend automatically (every 3–5 seconds), no manual refresh.
- **Anomaly event log/feed panel** — floating panel showing a scrollable feed of recent anomaly alerts with timestamps, severity badges, and affected callsigns.
- **Sortable/filterable aircraft data table** — a toggleable overlay table listing all tracked aircraft with sortable columns (callsign, altitude, speed, status).
- **Mini-chart sparklines** — per-aircraft altitude and speed trend sparklines visible in the telemetry drawer.
- **Browser notifications and/or audio alert** when a new anomaly is detected.
- **Top header metrics bar** displaying: active airborne aircraft count, detected anomaly tally, system status indicator, and UTC timestamp.
- **Interactive telemetry drawer/panel** on aircraft click: callsign, ICAO24, origin country, speed (knots), barometric altitude (meters), climb/descent rate (ft/min), squawk code, severity badge, anomaly rationale text, and altitude/speed sparkline charts.
- **Marker encoding:** cyan/green glowing markers for nominal flights; pulsing red/crimson high-contrast markers for anomalous flights with glow effects.
- **Responsive layout** that works on both desktop and tablet viewports.

### R4. Expanded Backend API
- `GET /api/telemetry` — Returns all active airborne vectors with kinematic parameters, anomaly flags, and trail history.
- `GET /api/flight/{icao24}` — Returns detailed kinematic history for a specific aircraft.
- `GET /api/anomalies` — Returns recent anomaly events (log with timestamps, severity, rationale, affected ICAO24/callsign).
- `GET /api/stats` — Returns aggregate statistics (total flights tracked, anomalies per category, uptime, cache health).
- `WebSocket /ws/telemetry` — Real-time push channel for live telemetry updates to the dashboard (preferred over polling if feasible).
- `GET /api/health` — System health and ingestion diagnostics.
- Dashboard served at `GET /` from static files.

### R5. Automated Verification Suite
- Unit tests verifying all three anomaly detection traps against boundary values and edge cases.
- Tests for null/None/NaN safety in ADS-B tuple parsing.
- API contract tests for all REST endpoints (response schema, status codes).
- Cache performance benchmark test (< 50ms retrieval).
- A `run.bat` launcher script (with CRLF line endings) that kills any existing process on port 8000, starts the server, and opens the browser.

## Acceptance Criteria

### Anomaly Engine Correctness
- [ ] Unit tests pass for all threshold conditions: squawks 7500/7600/7700 trigger alerts; vertical rate < -20.32 m/s triggers severe descent; velocity > 330 m/s below 10,000 m triggers overspeed; normal cruise vectors produce zero false positives.
- [ ] None/NaN/missing ADS-B fields handled safely without unhandled exceptions.

### API Completeness
- [ ] All six endpoints (`/api/telemetry`, `/api/flight/{icao24}`, `/api/anomalies`, `/api/stats`, `/ws/telemetry` or polling fallback, `/api/health`) return valid JSON with correct schemas.
- [ ] Cache retrieval latency < 50ms under local benchmark.
- [ ] Ingestion loop survives HTTP 429 and network timeouts via exponential backoff.

### Dashboard Visual & Interactive Quality
- [ ] Dashboard loads at `http://localhost:8000/` without JavaScript console errors.
- [ ] CartoDB Dark Matter tiles render correctly as the base map layer.
- [ ] Aircraft markers visually distinguish nominal (cyan/green glow) from anomalous (pulsing red/crimson glow) flights.
- [ ] Clicking an aircraft marker opens a detailed telemetry drawer showing callsign, ICAO, speed, altitude, vertical rate, squawk, anomaly status, and sparkline trend charts.
- [ ] Anomaly event log panel displays recent alerts with timestamps and severity badges.
- [ ] Aircraft data table is toggleable, sortable, and filterable.
- [ ] Aircraft markers animate smoothly between position updates.
- [ ] Flight trail lines render on the map from kinematic history.
- [ ] Top metrics bar displays live airborne count, anomaly tally, and system status.

### Launcher
- [ ] `run.bat` uses CRLF line endings, starts the server, and opens the browser when double-clicked on Windows.
