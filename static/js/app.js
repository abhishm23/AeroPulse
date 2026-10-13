/**
 * AeroPulse Master Application Controller
 * static/js/app.js - Bootstraps and coordinates all HUD subsystems:
 * TacticalMap, TacticalMarkers, TacticalTrails, TacticalPanels, TacticalSparklines,
 * TacticalAudio, and TacticalNetwork.
 */

(function(window) {
  'use strict';

  class AeroPulseApp {
    constructor() {
      this.initialized = false;
      this.knownAnomalies = new Set();
    }

    init() {
      if (this.initialized) return;
      this.initialized = true;

      console.log('[AeroPulse] Initializing Tactical HUD Airspace Surveillance System...');

      // 1. Initialize Map
      const map = window.AeroMap ? window.AeroMap.init('map') : null;

      // 2. Initialize Markers Engine
      if (window.AeroMarkers && map) {
        window.AeroMarkers.init(map, (flight) => {
          if (window.AeroPanels) {
            window.AeroPanels.openDrawer(flight);
          }
        });
      }

      // 3. Initialize Trails Engine
      if (window.AeroTrails && map) {
        window.AeroTrails.init(map);
      }

      // 4. Initialize UI Panels, Clocks, Hotkeys & Controls
      if (window.AeroPanels) {
        window.AeroPanels.init();
      }

      // 5. Initialize Web Audio unlock on first user interaction
      const unlockAudio = () => {
        if (window.AeroAudio) {
          window.AeroAudio.initAudio();
        }
        window.removeEventListener('click', unlockAudio);
        window.removeEventListener('keydown', unlockAudio);
      };
      window.addEventListener('click', unlockAudio);
      window.addEventListener('keydown', unlockAudio);

      // 6. Request Notification permission if supported
      if ('Notification' in window && Notification.permission === 'default') {
        const requestNotify = () => {
          try {
            Notification.requestPermission();
          } catch (e) {}
          window.removeEventListener('click', requestNotify);
        };
        window.addEventListener('click', requestNotify);
      }

      // 7. Initialize Dual-Mode Network Client (WebSocket + Polling Fallback)
      if (window.AeroNetwork) {
        window.AeroNetwork.init({
          onTelemetry: (payload, source) => {
            this.handleTelemetryUpdate(payload, source);
          },
          onAnomalies: (anomaliesList) => {
            if (window.AeroPanels) {
              window.AeroPanels.updateAnomalyFeed(anomaliesList);
            }
            this.checkForNewAnomalies(anomaliesList);
          },
          onConnectionChange: (mode) => {
            if (window.AeroPanels) {
              window.AeroPanels.updateHeader({}, mode);
            }
          }
        });
      }

      console.log('[AeroPulse] Subsystems online. Surveillance radar active.');
    }

    handleTelemetryUpdate(payload, source) {
      if (!payload) return;

      const aircraftList = payload.aircraft || payload.vectors || (Array.isArray(payload) ? payload : []);

      // 1. Update LERP Markers
      if (window.AeroMarkers) {
        window.AeroMarkers.update(aircraftList);
      }

      // 2. Update Flight Trails
      if (window.AeroTrails) {
        window.AeroTrails.update(aircraftList);
      }

      // 3. Update Header counters and KPI badges
      if (window.AeroPanels) {
        window.AeroPanels.updateHeader(payload, source);
        window.AeroPanels.updateTable(aircraftList);

        // If drawer is open, keep selected aircraft telemetry live
        const selectedIcao = window.AeroMarkers ? window.AeroMarkers.getSelectedIcao() : null;
        if (selectedIcao) {
          const updatedFlight = window.AeroMarkers.getAircraft(selectedIcao);
          if (updatedFlight && window.AeroPanels.isDrawerOpen) {
            window.AeroPanels.openDrawer(updatedFlight);
          }
        }
      }

      // 4. Extract anomalies from aircraft list if present
      const anomalies = [];
      aircraftList.forEach(ac => {
        if (ac.anomalies && Array.isArray(ac.anomalies)) {
          ac.anomalies.forEach(anom => {
            anomalies.push({
              ...anom,
              icao24: ac.icao24,
              callsign: ac.callsign,
              timestamp: anom.timestamp || ac.timestamp || (Date.now() / 1000)
            });
          });
        }
      });

      if (anomalies.length > 0) {
        this.checkForNewAnomalies(anomalies);
        if (window.AeroPanels) {
          window.AeroPanels.updateAnomalyFeed(anomalies);
        }
      }
    }

    checkForNewAnomalies(anomaliesList) {
      if (!Array.isArray(anomaliesList)) return;

      anomaliesList.forEach(anom => {
        const key = anom.icao24 + '_' + (anom.anomaly_type || anom.type || anom.rationale || '');
        if (!this.knownAnomalies.has(key)) {
          this.knownAnomalies.add(key);

          // Audio Alert Ping
          if (window.AeroAudio) {
            window.AeroAudio.playAnomalyAlert(anom.severity || 'CRITICAL');
          }

          // Browser Desktop Notification
          if ('Notification' in window && Notification.permission === 'granted') {
            try {
              new Notification('AEROPULSE ALERT: ' + (anom.callsign || anom.icao24 || 'UNKNOWN'), {
                body: (anom.severity || 'ALERT') + ': ' + (anom.rationale || 'Kinematic anomaly detected')
              });
            } catch (e) {}
          }
        }
      });
    }
  }

  // Auto-boot on DOM ready
  const app = new AeroPulseApp();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => app.init());
  } else {
    app.init();
  }

  window.AeroApp = app;
})(window);
