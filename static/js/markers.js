/**
 * AeroPulse Aircraft Marker & Kinematic Interpolation Engine
 * static/js/markers.js - 60 FPS LERP coordinates, shortest-arc heading rotation,
 * directional rotating SVG icons, and anomaly crimson pulse rings.
 */

(function(window) {
  'use strict';

  class TacticalMarkerEngine {
    constructor() {
      this.map = null;
      this.markersLayer = null;
      this.activeMarkers = new Map(); // icao24 -> { marker, iconEl, currentLat, currentLon, targetLat, targetLon, startLat, startLon, currentHeading, targetHeading, startHeading, startTime, duration, data, isAnomalous, isSelected }
      this.selectedIcao24 = null;
      this.onSelectCallback = null;
      this.animFrameId = null;
      this.isAnimating = false;
    }

    /**
     * Initializes marker layer group on map and starts 60fps LERP loop
     */
    init(map, onSelectCallback) {
      this.map = map;
      this.onSelectCallback = onSelectCallback;
      this.markersLayer = L.layerGroup().addTo(this.map);
      this.startAnimationLoop();
    }

    /**
     * Creates custom Leaflet divIcon wrapping tactical SVG aircraft
     */
    _createMarkerIcon(heading = 0, isAnomalous = false, isSelected = false) {
      const statusClass = isAnomalous ? 'anomalous' : 'nominal';
      const pulseHtml = isAnomalous ? '<div class="marker-pulse-ring"></div>' : '';
      const reticleHtml = isSelected ? '<div class="marker-selected-reticle"></div>' : '';

      const html = `
        <div class="aircraft-marker ${statusClass}" style="transform: rotate(${heading}deg);">
          <svg viewBox="0 0 32 32" class="aircraft-svg">
            <path d="M16 2 L22 14 L30 18 L22 20 L22 27 L16 24 L10 27 L10 20 L2 18 L10 14 Z"/>
          </svg>
          ${pulseHtml}
          ${reticleHtml}
        </div>
      `;

      return L.divIcon({
        className: 'aircraft-marker-wrapper',
        html: html,
        iconSize: [32, 32],
        iconAnchor: [16, 16]
      });
    }

    /**
     * Ingests latest telemetry vector array and schedules LERP tweening
     * @param {Object[]} aircraftList - Array of AircraftDetail objects
     * @param {number} updateIntervalMs - Duration of tweening cycle (typically 3000-4000ms)
     */
    updateAircraft(aircraftList, updateIntervalMs = 3500) {
      if (!this.map || !this.markersLayer) return;

      const now = performance.now();
      const currentIcaos = new Set();

      (aircraftList || []).forEach(item => {
        if (!item || !item.icao24) return;
        const icao = item.icao24.toLowerCase().trim();

        // Validate coordinate bounds (reject Null Island (0,0) and invalid coordinates)
        const lat = parseFloat(item.latitude);
        const lon = parseFloat(item.longitude);
        if (isNaN(lat) || isNaN(lon)) return;
        if (lat === 0.0 && lon === 0.0) return;
        if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return;

        currentIcaos.add(icao);

        // Safe heading normalization (0 to 360 deg)
        let targetHeading = 0;
        if (typeof item.true_track === 'number' && !isNaN(item.true_track)) {
          targetHeading = ((item.true_track % 360) + 360) % 360;
        }

        const isAnomalous = Boolean(item.has_anomaly || (item.status && item.status !== 'NOMINAL'));
        const isSelected = (this.selectedIcao24 === icao);

        if (this.activeMarkers.has(icao)) {
          // UPDATE EXISTING MARKER
          const entry = this.activeMarkers.get(icao);

          // Update tween start and targets
          entry.startLat = entry.currentLat;
          entry.startLon = entry.currentLon;
          entry.targetLat = lat;
          entry.targetLon = lon;

          entry.startHeading = entry.currentHeading;
          entry.targetHeading = targetHeading;

          entry.startTime = now;
          entry.duration = updateIntervalMs;
          entry.data = item;

          // Re-render icon only if anomaly or selection status changed
          if (entry.isAnomalous !== isAnomalous || entry.isSelected !== isSelected) {
            entry.isAnomalous = isAnomalous;
            entry.isSelected = isSelected;
            entry.marker.setIcon(this._createMarkerIcon(entry.currentHeading, isAnomalous, isSelected));
            entry.iconEl = entry.marker.getElement()?.querySelector('.aircraft-marker');
          }
        } else {
          // CREATE NEW MARKER
          const markerIcon = this._createMarkerIcon(targetHeading, isAnomalous, isSelected);
          const marker = L.marker([lat, lon], {
            icon: markerIcon,
            zIndexOffset: isAnomalous ? 1000 : 100
          }).addTo(this.markersLayer);

          marker.on('click', (e) => {
            L.DomEvent.stopPropagation(e);
            this.selectAircraft(icao);
          });

          const entry = {
            marker,
            iconEl: marker.getElement()?.querySelector('.aircraft-marker'),
            currentLat: lat,
            currentLon: lon,
            startLat: lat,
            startLon: lon,
            targetLat: lat,
            targetLon: lon,
            currentHeading: targetHeading,
            startHeading: targetHeading,
            targetHeading: targetHeading,
            startTime: now,
            duration: updateIntervalMs,
            data: item,
            isAnomalous,
            isSelected
          };

          this.activeMarkers.set(icao, entry);
        }
      });

      // Prune stale markers no longer present in telemetry snapshot
      for (const [icao, entry] of this.activeMarkers.entries()) {
        if (!currentIcaos.has(icao)) {
          this.markersLayer.removeLayer(entry.marker);
          this.activeMarkers.delete(icao);
        }
      }
    }

    /**
     * 60fps RequestAnimationFrame LERP Animation Loop
     */
    startAnimationLoop() {
      if (this.isAnimating) return;
      this.isAnimating = true;

      const animate = (timestamp) => {
        for (const [_, entry] of this.activeMarkers.entries()) {
          const elapsed = timestamp - entry.startTime;
          const progress = Math.min(Math.max(elapsed / entry.duration, 0), 1.0);

          // Linear interpolation for coordinates
          const newLat = entry.startLat + (entry.targetLat - entry.startLat) * progress;
          const newLon = entry.startLon + (entry.targetLon - entry.startLon) * progress;
          entry.currentLat = newLat;
          entry.currentLon = newLon;

          // Shortest angular arc heading interpolation: ((target - start + 540) % 360) - 180
          const diffHeading = ((entry.targetHeading - entry.startHeading + 540) % 360) - 180;
          const newHeading = ((entry.startHeading + diffHeading * progress) % 360 + 360) % 360;
          entry.currentHeading = newHeading;

          // Update Leaflet marker position
          entry.marker.setLatLng([newLat, newLon]);

          // Update SVG rotation transform
          if (!entry.iconEl) {
            entry.iconEl = entry.marker.getElement()?.querySelector('.aircraft-marker');
          }
          if (entry.iconEl) {
            entry.iconEl.style.transform = `rotate(${newHeading.toFixed(1)}deg)`;
          }
        }

        this.animFrameId = requestAnimationFrame(animate);
      };

      this.animFrameId = requestAnimationFrame(animate);
    }

    stopAnimationLoop() {
      if (this.animFrameId) {
        cancelAnimationFrame(this.animFrameId);
        this.animFrameId = null;
      }
      this.isAnimating = false;
    }

    /**
     * Marks an aircraft as selected and updates visual reticle
     * @param {string} icao24
     */
    selectAircraft(icao24) {
      const cleanIcao = (icao24 || '').toLowerCase().trim();
      if (this.selectedIcao24 === cleanIcao && cleanIcao) {
        // Already selected, re-invoke callback
        if (this.activeMarkers.has(cleanIcao) && this.onSelectCallback) {
          this.onSelectCallback(this.activeMarkers.get(cleanIcao).data);
        }
        return;
      }

      // Clear previous selection
      if (this.selectedIcao24 && this.activeMarkers.has(this.selectedIcao24)) {
        const prev = this.activeMarkers.get(this.selectedIcao24);
        prev.isSelected = false;
        prev.marker.setIcon(this._createMarkerIcon(prev.currentHeading, prev.isAnomalous, false));
        prev.iconEl = prev.marker.getElement()?.querySelector('.aircraft-marker');
      }

      this.selectedIcao24 = cleanIcao || null;

      // Apply new selection
      if (cleanIcao && this.activeMarkers.has(cleanIcao)) {
        const entry = this.activeMarkers.get(cleanIcao);
        entry.isSelected = true;
        entry.marker.setIcon(this._createMarkerIcon(entry.currentHeading, entry.isAnomalous, true));
        entry.iconEl = entry.marker.getElement()?.querySelector('.aircraft-marker');

        if (this.onSelectCallback) {
          this.onSelectCallback(entry.data);
        }
      }
    }

    clearSelection() {
      if (this.selectedIcao24 && this.activeMarkers.has(this.selectedIcao24)) {
        const prev = this.activeMarkers.get(this.selectedIcao24);
        prev.isSelected = false;
        prev.marker.setIcon(this._createMarkerIcon(prev.currentHeading, prev.isAnomalous, false));
        prev.iconEl = prev.marker.getElement()?.querySelector('.aircraft-marker');
      }
      this.selectedIcao24 = null;
    }

    getAircraft(icao24) {
      const entry = this.activeMarkers.get((icao24 || '').toLowerCase().trim());
      return entry ? entry.data : null;
    }

    getSelectedIcao() {
      return this.selectedIcao24;
    }
  }

  window.AeroMarkers = new TacticalMarkerEngine();
})(window);
