/**
 * AeroPulse Map Manager
 * static/js/map.js - Leaflet Map Integration with CartoDB Dark Matter
 * Provides full-viewport tactical airspace visualization layer.
 */

(function(window) {
  'use strict';

  class TacticalMapManager {
    constructor() {
      this.map = null;
      this.defaultCenter = [48.0, 14.0]; // Central European airspace
      this.defaultZoom = 5;
      this.tileLayer = null;
    }

    /**
     * Initializes the Leaflet map container and CartoDB Dark Matter base layer
     */
    init(containerId = 'map') {
      if (typeof L === 'undefined') {
        console.error('[AeroMap] Leaflet.js (L) is not loaded.');
        return null;
      }

      // Initialize Leaflet map
      this.map = L.map(containerId, {
        center: this.defaultCenter,
        zoom: this.defaultZoom,
        minZoom: 3,
        maxZoom: 18,
        zoomControl: false, // We reposition custom zoom control bottom-right
        attributionControl: true
      });

      // CartoDB Dark Matter Tile Layer
      this.tileLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 19,
        minZoom: 3
      }).addTo(this.map);

      // Reposition zoom controls to bottom-right
      L.control.zoom({ position: 'bottomright' }).addTo(this.map);

      // Handle window resize
      window.addEventListener('resize', () => {
        if (this.map) {
          this.map.invalidateSize();
        }
      });

      return this.map;
    }

    getMap() {
      return this.map;
    }

    /**
     * Smoothly flies camera to target flight coordinate
     * @param {number} lat
     * @param {number} lon
     * @param {number} zoom
     */
    flyToFlight(lat, lon, zoom = 8) {
      if (!this.map || typeof lat !== 'number' || typeof lon !== 'number') return;
      if (isNaN(lat) || isNaN(lon)) return;
      this.map.flyTo([lat, lon], zoom, {
        duration: 1.2,
        easeLinearity: 0.25
      });
    }

    /**
     * Resets view to default tactical European airspace bounding
     */
    resetView() {
      if (!this.map) return;
      this.map.flyTo(this.defaultCenter, this.defaultZoom, {
        duration: 1.0
      });
    }

    /**
     * Force Leaflet map layout re-calculation
     */
    invalidateSize() {
      if (this.map) {
        this.map.invalidateSize();
      }
    }
  }

  window.AeroMap = new TacticalMapManager();
})(window);
