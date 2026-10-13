# AeroPulse — Real-Time Flight Telemetry Anomaly Detection HUD

High-frequency flight telemetry streaming and anomaly detection platform engineered with FastAPI, WebSockets, asyncio, and Leaflet.js.

## Overview
AeroPulse ingests real-time aircraft state vectors, detects flight envelope deviations (pitch, roll, altitude anomalies), and renders live telemetry onto a tactical tactical map display.

## Architecture
- **Backend**: FastAPI, asyncio WebSockets, scientific Python math kernels
- **Frontend**: Leaflet.js radar/flight tracking map, tactical HUD metrics
- **Testing**: Automated end-to-end integration and adversarial anomaly test suite

## Quick Start
```bash
run.bat
# Access web dashboard at http://localhost:8000
```
