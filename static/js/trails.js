/**
 * AeroPulse Flight Path Trail Polyline Renderer
 * static/js/trails.js - Renders breadcrumb trajectories from ring buffer history
 * Glowing neon cyan (nominal) and solid crimson (anomalous) flight trails.
 */

(function(window) {
  'use strict';

  class TacticalTrailRenderer {
    constructor() {
      this.map = null;
      this.trailsLayer = null;
      this.activePolylines = new Map(); // icao24 -> L.polyline
      this.enabled = true;
    }

    /**
     * Initializes polyline layer group on Leaflet map
     */
    init(map) {
      this.map = map;
      this.trailsLayer = L.layerGroup().addTo(this.map);
    }

    /**
     * Ingests latest telemetry snapshot and updates flight path polylines
     * @param {Object[]} aircraftList - Array of AircraftDetail
     */
    updateTrails(aircraftList) {
      if (!this.map || !this.trailsLayer || !this.enabled) return;

      const currentIcaos = new Set();

      (aircraftList || []).forEach(item => {
        if (!item || !item.icao24) return;
        const icao = item.icao24.toLowerCase().trim();

        // Extract trail history coordinates
        const rawTrail = item.trail || item.trail_history || item.history || [];
        if (!Array.isArray(rawTrail) || rawTrail.length < 2) {
          // Insufficient points for a polyline
          if (this.activePolylines.has(icao)) {
            this.trailsLayer.removeLayer(this.activePolylines.get(icao));
            this.activePolylines.delete(icao);
          }
          return;
        }

        const latLngs = [];
        for (const pt of rawTrail) {
          let lat = null;
          let lon = null;
          if (Array.isArray(pt) && pt.length >= 2) {
            lat = parseFloat(pt[0]);
            lon = parseFloat(pt[1]);
          } else if (pt && typeof pt === 'object') {
            lat = parseFloat(pt.lat ?? pt.latitude);
            lon = parseFloat(pt.lon ?? pt.longitude);
          }

          if (lat !== null && lon !== null && !isNaN(lat) && !isNaN(lon)) {
            if (!(lat === 0.0 && lon === 0.0) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180) {
              latLngs.push([lat, lon]);
            }
          }
        }

        if (latLngs.length < 2) {
          if (this.activePolylines.has(icao)) {
            this.trailsLayer.removeLayer(this.activePolylines.get(icao));
            this.activePolylines.delete(icao);
          }
          return;
        }

        currentIcaos.add(icao);
        const isAnomalous = Boolean(item.has_anomaly || (item.status && item.status !== 'NOMINAL'));

        const style = isAnomalous ? {
          color: '#ff003c',
          weight: 2.2,
          opacity: 0.85,
          dashArray: null
        } : {
          color: '#00f3ff',
          weight: 1.8,
          opacity: 0.55,
          dashArray: '4, 4'
        };

        if (this.activePolylines.has(icao)) {
          const polyline = this.activePolylines.get(icao);
          polyline.setLatLngs(latLngs);
          polyline.setStyle(style);
        } else {
          const polyline = L.polyline(latLngs, style).addTo(this.trailsLayer);
          this.activePolylines.set(icao, polyline);
        }
      });

      // Prune dead flight polylines
      for (const [icao, polyline] of this.activePolylines.entries()) {
        if (!currentIcaos.has(icao)) {
          this.trailsLayer.removeLayer(polyline);
          this.activePolylines.delete(icao);
        }
      }
    }

    /**
     * Toggles trail rendering on or off
     */
    toggleTrails() {
      this.enabled = !this.enabled;
      if (!this.enabled) {
        this.clear();
      }
      return this.enabled;
    }

    /**
     * Clears all rendered polylines from the map
     */
    clear() {
      if (this.trailsLayer) {
        this.trailsLayer.clearLayers();
      }
      this.activePolylines.clear();
    }
  }

  window.AeroTrails = new TacticalTrailRenderer();
})(window);
