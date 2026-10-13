/**
 * AeroPulse HUD Panels & UI Component Coordinator
 * static/js/panels.js - Header metrics bar, UTC Zulu clock, Anomaly Event Feed,
 * Sortable/Filterable Data Table overlay, and Interactive Telemetry Drawer.
 */

(function(window) {
  'use strict';

  class TacticalPanelsManager {
    constructor() {
      // DOM Elements Cache
      this.el = {};

      // Table state
      this.tableData = [];
      this.tableFilter = 'ALL'; // 'ALL' | 'NOMINAL' | 'ANOMALIES'
      this.tableSearch = '';
      this.sortCol = 'callsign';
      this.sortAsc = true;
      this.isTableOpen = false;

      // Drawer state
      this.isDrawerOpen = false;
      this.currentFlight = null;

      // Anomaly Feed state
      this.anomaliesList = [];
    }

    /**
     * Initializes DOM bindings, clock loop, and event listeners
     */
    init() {
      this._cacheElements();
      this._startUtcClock();
      this._bindEvents();
    }

    _cacheElements() {
      this.el = {
        // Top Header
        airborneCount: document.getElementById('airborneCount'),
        anomalyCount: document.getElementById('anomalyCount'),
        systemStatus: document.getElementById('systemStatus'),
        connectionModeText: document.getElementById('connectionModeText'),
        connectionBeacon: document.getElementById('connectionBeacon'),
        utcClock: document.getElementById('utcClock'),
        audioToggleBtn: document.getElementById('audioToggleBtn'),
        crtToggleBtn: document.getElementById('crtToggleBtn'),
        tableToggleBtn: document.getElementById('tableToggleBtn'),
        centerAirspaceBtn: document.getElementById('centerAirspaceBtn'),
        crtOverlay: document.getElementById('crtOverlay'),

        // Anomaly Feed
        anomalyFeedPanel: document.getElementById('anomalyFeedPanel'),
        anomalyFeedList: document.getElementById('anomalyFeedList'),
        alertBadgeCount: document.getElementById('alertBadgeCount'),
        feedEmptyState: document.getElementById('feedEmptyState'),

        // Telemetry Drawer
        telemetryDrawer: document.getElementById('telemetryDrawer'),
        drawerCloseBtn: document.getElementById('drawerCloseBtn'),
        drawerCallsign: document.getElementById('drawerCallsign'),
        drawerIcao: document.getElementById('drawerIcao'),
        drawerCountry: document.getElementById('drawerCountry'),
        drawerDiagnosticBanner: document.getElementById('drawerDiagnosticBanner'),
        drawerDiagnosticLabel: document.getElementById('drawerDiagnosticLabel'),
        drawerRationaleText: document.getElementById('drawerRationaleText'),
        drawerAltFt: document.getElementById('drawerAltFt'),
        drawerAltM: document.getElementById('drawerAltM'),
        drawerSpeedKts: document.getElementById('drawerSpeedKts'),
        drawerSpeedMs: document.getElementById('drawerSpeedMs'),
        drawerClimbFpm: document.getElementById('drawerClimbFpm'),
        drawerClimbMs: document.getElementById('drawerClimbMs'),
        drawerSquawk: document.getElementById('drawerSquawk'),
        drawerSquawkType: document.getElementById('drawerSquawkType'),
        drawerHeading: document.getElementById('drawerHeading'),
        drawerHeadingCardinal: document.getElementById('drawerHeadingCardinal'),
        drawerCoords: document.getElementById('drawerCoords'),
        drawerLastContact: document.getElementById('drawerLastContact'),
        sparklineAltCurrent: document.getElementById('sparklineAltCurrent'),
        sparklineSpeedCurrent: document.getElementById('sparklineSpeedCurrent'),
        altSparkline: document.getElementById('altSparkline'),
        speedSparkline: document.getElementById('speedSparkline'),
        cardAltitude: document.getElementById('cardAltitude'),
        cardSpeed: document.getElementById('cardSpeed'),
        cardClimb: document.getElementById('cardClimb'),
        cardSquawk: document.getElementById('cardSquawk'),

        // Aircraft Data Table Overlay
        aircraftTableOverlay: document.getElementById('aircraftTableOverlay'),
        tableCloseBtn: document.getElementById('tableCloseBtn'),
        tableSearchInput: document.getElementById('tableSearchInput'),
        filterAll: document.getElementById('filterAll'),
        filterNominal: document.getElementById('filterNominal'),
        filterAnomalies: document.getElementById('filterAnomalies'),
        pillCountAll: document.getElementById('pillCountAll'),
        pillCountNominal: document.getElementById('pillCountNominal'),
        pillCountAnomalies: document.getElementById('pillCountAnomalies'),
        aircraftTable: document.getElementById('aircraftTable'),
        aircraftTableBody: document.getElementById('aircraftTableBody')
      };
    }

    _bindEvents() {
      // Audio Mute Toggle
      if (this.el.audioToggleBtn) {
        this.el.audioToggleBtn.addEventListener('click', () => {
          if (window.AeroAudio) {
            const isMuted = window.AeroAudio.toggleMute();
            this.updateAudioButtonState(isMuted);
          }
        });
        if (window.AeroAudio) {
          this.updateAudioButtonState(window.AeroAudio.isMuted());
        }
      }

      // CRT Overlay Toggle
      if (this.el.crtToggleBtn && this.el.crtOverlay) {
        this.el.crtToggleBtn.addEventListener('click', () => {
          this.el.crtOverlay.classList.toggle('disabled');
          const isEnabled = !this.el.crtOverlay.classList.contains('disabled');
          this.el.crtToggleBtn.textContent = isEnabled ? '📺 CRT [ON]' : '📺 CRT [OFF]';
        });
      }

      // Data Grid Toggle
      if (this.el.tableToggleBtn) {
        this.el.tableToggleBtn.addEventListener('click', () => this.toggleTable());
      }
      if (this.el.tableCloseBtn) {
        this.el.tableCloseBtn.addEventListener('click', () => this.closeTable());
      }

      // Center Airspace Button
      if (this.el.centerAirspaceBtn) {
        this.el.centerAirspaceBtn.addEventListener('click', () => {
          if (window.AeroMap) window.AeroMap.resetView();
        });
      }

      // Drawer Close Button
      if (this.el.drawerCloseBtn) {
        this.el.drawerCloseBtn.addEventListener('click', () => this.closeDrawer());
      }

      // Table Search Input (safe string matching)
      if (this.el.tableSearchInput) {
        this.el.tableSearchInput.addEventListener('input', (e) => {
          this.tableSearch = (e.target.value || '').trim();
          this.renderTable();
        });
      }

      // Table Filter Pills
      [this.el.filterAll, this.el.filterNominal, this.el.filterAnomalies].forEach(pill => {
        if (!pill) return;
        pill.addEventListener('click', (e) => {
          const filter = e.target.closest('.filter-pill')?.dataset.filter;
          if (filter) {
            this.setTableFilter(filter);
          }
        });
      });

      // Table Column Sorting
      if (this.el.aircraftTable) {
        const headers = this.el.aircraftTable.querySelectorAll('th[data-col]');
        headers.forEach(th => {
          th.addEventListener('click', () => {
            const col = th.dataset.col;
            if (this.sortCol === col) {
              this.sortAsc = !this.sortAsc;
            } else {
              this.sortCol = col;
              this.sortAsc = true;
            }
            this._updateSortHeaders();
            this.renderTable();
          });
        });
      }

      // Global Keydown Shortcuts
      window.addEventListener('keydown', (e) => {
        // Ignore if focus is in an input
        if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) {
          if (e.key === 'Escape') {
            document.activeElement.blur();
          }
          return;
        }

        if (e.key === 'Escape') {
          if (this.isTableOpen) this.closeTable();
          if (this.isDrawerOpen) this.closeDrawer();
        } else if (e.key === 't' || e.key === 'T') {
          this.toggleTable();
        } else if (e.key === 'm' || e.key === 'M') {
          if (window.AeroAudio) {
            const isMuted = window.AeroAudio.toggleMute();
            this.updateAudioButtonState(isMuted);
          }
        } else if (e.key === 'c' || e.key === 'C') {
          if (this.el.crtOverlay && this.el.crtToggleBtn) {
            this.el.crtOverlay.classList.toggle('disabled');
            const isEnabled = !this.el.crtOverlay.classList.contains('disabled');
            this.el.crtToggleBtn.textContent = isEnabled ? '📺 CRT [ON]' : '📺 CRT [OFF]';
          }
        }
      });
    }

    _startUtcClock() {
      const updateClock = () => {
        if (this.el.utcClock) {
          const now = new Date();
          const year = now.getUTCFullYear();
          const month = String(now.getUTCMonth() + 1).padStart(2, '0');
          const day = String(now.getUTCDate()).padStart(2, '0');
          const hours = String(now.getUTCHours()).padStart(2, '0');
          const minutes = String(now.getUTCMinutes()).padStart(2, '0');
          const seconds = String(now.getUTCSeconds()).padStart(2, '0');
          this.el.utcClock.textContent = `${year}-${month}-${day} ${hours}:${minutes}:${seconds} UTC`;
        }
      };
      updateClock();
      setInterval(updateClock, 1000);
    }

    updateAudioButtonState(isMuted) {
      if (!this.el.audioToggleBtn) return;
      this.el.audioToggleBtn.textContent = isMuted ? '🔇 AUDIO [MUTED]' : '🔊 AUDIO [ON]';
      if (isMuted) {
        this.el.audioToggleBtn.classList.add('alert');
      } else {
        this.el.audioToggleBtn.classList.remove('alert');
      }
    }

    /**
     * Updates header status and KPI counters
     */
    updateHeader(data, connectionMode = 'WS') {
      const totalAirborne = data.airborne_count ?? data.airborne ?? 0;
      const totalAnomalies = data.anomaly_count ?? data.anomalies ?? 0;

      if (this.el.airborneCount) {
        this.el.airborneCount.textContent = totalAirborne.toLocaleString();
      }

      if (this.el.anomalyCount) {
        this.el.anomalyCount.textContent = totalAnomalies.toLocaleString();
        if (totalAnomalies > 0) {
          this.el.anomalyCount.classList.remove('nominal');
          this.el.anomalyCount.classList.add('alert');
        } else {
          this.el.anomalyCount.classList.remove('alert');
          this.el.anomalyCount.classList.add('nominal');
        }
      }

      if (this.el.systemStatus) {
        if (totalAnomalies > 0) {
          this.el.systemStatus.textContent = 'ALERT';
          this.el.systemStatus.classList.remove('nominal');
          this.el.systemStatus.classList.add('alert');
        } else {
          this.el.systemStatus.textContent = 'NOMINAL';
          this.el.systemStatus.classList.remove('alert');
          this.el.systemStatus.classList.add('nominal');
        }
      }

      // Connection Mode Beacon
      if (this.el.connectionModeText && this.el.connectionBeacon) {
        if (connectionMode === 'WS') {
          this.el.connectionModeText.textContent = 'WS: LIVE';
          this.el.connectionBeacon.className = 'status-beacon-dot';
        } else if (connectionMode === 'POLLING') {
          this.el.connectionModeText.textContent = 'FALLBACK POLLING';
          this.el.connectionBeacon.className = 'status-beacon-dot warning';
        } else {
          this.el.connectionModeText.textContent = 'RECONNECTING...';
          this.el.connectionBeacon.className = 'status-beacon-dot alert';
        }
      }
    }

    /**
     * Updates the Anomaly Event Feed
     * @param {Object[]} anomalies - Array of anomaly event objects
     */
    updateAnomalyFeed(anomalies) {
      this.anomaliesList = Array.isArray(anomalies) ? anomalies : [];
      const count = this.anomaliesList.length;

      if (this.el.alertBadgeCount) {
        this.el.alertBadgeCount.textContent = count;
      }

      if (!this.el.anomalyFeedList) return;

      if (count === 0) {
        this.el.anomalyFeedList.innerHTML = '<div class="anomaly-empty-state">ALL AIRSPACE VECTORS NOMINAL</div>';
        return;
      }

      // Render cards
      let html = '';
      this.anomaliesList.slice(0, 50).forEach(anom => {
        const sev = (anom.severity || 'WARNING').toUpperCase();
        const callsign = anom.callsign || anom.icao24?.toUpperCase() || 'UNKNOWN';
        const icao = (anom.icao24 || '').toUpperCase();
        const timeStr = anom.timestamp ? new Date(anom.timestamp * 1000).toISOString().substr(11, 8) + ' UTC' : 'LIVE';
        const rationale = anom.rationale || 'Threshold trap triggered';

        html += `
          <div class="anomaly-card ${sev}" data-icao="${icao.toLowerCase()}">
            <div class="anomaly-card-top">
              <span class="anomaly-callsign">${callsign}</span>
              <span class="badge badge-${sev.toLowerCase()}">${sev}</span>
            </div>
            <div class="anomaly-rationale">${rationale}</div>
            <div class="anomaly-card-footer">
              <span class="anomaly-time">${timeStr} [${icao}]</span>
              <span class="anomaly-focus-hint">🎯 FOCUS VECTOR</span>
            </div>
          </div>
        `;
      });

      this.el.anomalyFeedList.innerHTML = html;

      // Attach click listeners to cards to focus flight
      this.el.anomalyFeedList.querySelectorAll('.anomaly-card').forEach(card => {
        card.addEventListener('click', () => {
          const icao = card.dataset.icao;
          if (icao && window.AeroMarkers) {
            const flight = window.AeroMarkers.getAircraft(icao);
            if (flight) {
              if (window.AeroMap && typeof flight.latitude === 'number' && typeof flight.longitude === 'number') {
                window.AeroMap.flyToFlight(flight.latitude, flight.longitude, 9);
              }
              window.AeroMarkers.selectAircraft(icao);
            }
          }
        });
      });
    }

    /**
     * Opens Telemetry Drawer and populates flight data & canvas sparklines
     * @param {Object} flight - AircraftDetail object
     */
    openDrawer(flight) {
      if (!flight) return;
      this.currentFlight = flight;
      this.isDrawerOpen = true;

      if (this.el.telemetryDrawer) {
        this.el.telemetryDrawer.classList.add('open');
      }

      // Callsign / ICAO / Country
      const callsign = flight.callsign || flight.icao24?.toUpperCase() || 'UNKNOWN';
      const icao = (flight.icao24 || '------').toUpperCase();
      const country = (flight.origin_country || 'UNKNOWN NATION').toUpperCase();

      if (this.el.drawerCallsign) this.el.drawerCallsign.textContent = callsign;
      if (this.el.drawerIcao) this.el.drawerIcao.textContent = `ICAO: ${icao}`;
      if (this.el.drawerCountry) this.el.drawerCountry.textContent = country;

      // Status & Rationale Banner
      const isAnomalous = Boolean(flight.has_anomaly || (flight.status && flight.status !== 'NOMINAL'));
      const status = (flight.status || 'NOMINAL').toUpperCase();

      if (this.el.drawerDiagnosticBanner && this.el.drawerDiagnosticLabel && this.el.drawerRationaleText) {
        if (isAnomalous) {
          this.el.drawerDiagnosticBanner.className = 'drawer-diagnostic-banner alert';
          this.el.drawerDiagnosticLabel.textContent = `STATUS: ${status} ALERT`;

          const rationales = (flight.anomalies || []).map(a => a.rationale).filter(Boolean);
          this.el.drawerRationaleText.textContent = rationales.length > 0
            ? rationales.join(' • ')
            : 'Kinematic flight envelope threshold trap triggered.';
        } else {
          this.el.drawerDiagnosticBanner.className = 'drawer-diagnostic-banner nominal';
          this.el.drawerDiagnosticLabel.textContent = 'STATUS: NOMINAL FLIGHT PROFILE';
          this.el.drawerRationaleText.textContent = 'All kinematic parameters within operational envelope. Zero traps flagged.';
        }
      }

      // Barometric Altitude (Dual units: ft & m)
      const altFt = flight.alt_ft ?? (typeof flight.baro_altitude === 'number' ? Math.round(flight.baro_altitude * 3.28084) : null);
      const altM = typeof flight.baro_altitude === 'number' ? Math.round(flight.baro_altitude) : null;
      if (this.el.drawerAltFt) this.el.drawerAltFt.textContent = altFt !== null ? `${altFt.toLocaleString()} ft` : '--- ft';
      if (this.el.drawerAltM) this.el.drawerAltM.textContent = altM !== null ? `${altM.toLocaleString()} m` : '--- m';

      // Speed (Dual units: kts & m/s)
      const speedKts = flight.speed_kts ?? (typeof flight.velocity === 'number' ? Math.round(flight.velocity * 1.943844) : null);
      const speedMs = typeof flight.velocity === 'number' ? Math.round(flight.velocity) : null;
      if (this.el.drawerSpeedKts) this.el.drawerSpeedKts.textContent = speedKts !== null ? `${speedKts.toLocaleString()} kts` : '--- kts';
      if (this.el.drawerSpeedMs) this.el.drawerSpeedMs.textContent = speedMs !== null ? `${speedMs.toLocaleString()} m/s` : '--- m/s';

      // Vertical Rate (Dual units: ft/min & m/s)
      const climbFpm = flight.climb_fpm ?? (typeof flight.vertical_rate === 'number' ? Math.round(flight.vertical_rate * 196.85) : null);
      const climbMs = typeof flight.vertical_rate === 'number' ? flight.vertical_rate.toFixed(1) : null;
      if (this.el.drawerClimbFpm) {
        const sign = climbFpm > 0 ? '+' : '';
        this.el.drawerClimbFpm.textContent = climbFpm !== null ? `${sign}${climbFpm.toLocaleString()} ft/min` : '--- ft/min';
      }
      if (this.el.drawerClimbMs) {
        const sign = (flight.vertical_rate || 0) > 0 ? '+' : '';
        this.el.drawerClimbMs.textContent = climbMs !== null ? `${sign}${climbMs} m/s` : '--- m/s';
      }

      // Highlight cards if anomaly criteria met
      const hasDescentTrap = (flight.vertical_rate !== null && flight.vertical_rate < -20.32);
      const hasSpeedTrap = (flight.velocity !== null && flight.velocity > 330.0 && (flight.baro_altitude || 0) < 10000);
      const hasSquawkTrap = ['7500', '7600', '7700'].includes((flight.squawk || '').trim());

      if (this.el.cardClimb) {
        if (hasDescentTrap) this.el.cardClimb.classList.add('highlight-crimson');
        else this.el.cardClimb.classList.remove('highlight-crimson');
      }

      if (this.el.cardSpeed) {
        if (hasSpeedTrap) this.el.cardSpeed.classList.add('highlight-crimson');
        else this.el.cardSpeed.classList.remove('highlight-crimson');
      }

      // Squawk
      const squawk = flight.squawk || '----';
      if (this.el.drawerSquawk) this.el.drawerSquawk.textContent = squawk;
      if (this.el.drawerSquawkType) {
        if (squawk === '7500') this.el.drawerSquawkType.textContent = 'HIJACK / UNLAWFUL INT';
        else if (squawk === '7600') this.el.drawerSquawkType.textContent = 'RADIO FAILURE';
        else if (squawk === '7700') this.el.drawerSquawkType.textContent = 'GENERAL EMERGENCY';
        else this.el.drawerSquawkType.textContent = 'STANDARD TRANSPONDER';
      }
      if (this.el.cardSquawk) {
        if (hasSquawkTrap) this.el.cardSquawk.classList.add('highlight-crimson');
        else this.el.cardSquawk.classList.remove('highlight-crimson');
      }

      // Heading & Cardinal direction
      const heading = typeof flight.true_track === 'number' ? Math.round(flight.true_track) : null;
      if (this.el.drawerHeading) this.el.drawerHeading.textContent = heading !== null ? `${heading}°` : '---°';
      if (this.el.drawerHeadingCardinal) {
        this.el.drawerHeadingCardinal.textContent = heading !== null ? this._toCardinal(heading) : 'NORTH';
      }

      // Coordinates
      if (this.el.drawerCoords) {
        const lat = typeof flight.latitude === 'number' ? flight.latitude.toFixed(4) : '--.----';
        const lon = typeof flight.longitude === 'number' ? flight.longitude.toFixed(4) : '--.----';
        this.el.drawerCoords.textContent = `${lat}°, ${lon}°`;
      }

      // Canvas Sparklines
      const trail = flight.trail || flight.trail_history || flight.history || [];
      if (window.AeroSparklines) {
        if (this.el.altSparkline) {
          window.AeroSparklines.renderAltitude(this.el.altSparkline, trail);
        }
        if (this.el.speedSparkline) {
          window.AeroSparklines.renderSpeed(this.el.speedSparkline, trail, hasSpeedTrap);
        }
      }

      if (this.el.sparklineAltCurrent) {
        this.el.sparklineAltCurrent.textContent = altFt !== null ? `${altFt.toLocaleString()} ft` : '--- ft';
      }
      if (this.el.sparklineSpeedCurrent) {
        this.el.sparklineSpeedCurrent.textContent = speedKts !== null ? `${speedKts.toLocaleString()} kts` : '--- kts';
      }

      // Notify map of layout change
      if (window.AeroMap) {
        setTimeout(() => window.AeroMap.invalidateSize(), 300);
      }
    }

    closeDrawer() {
      this.isDrawerOpen = false;
      this.currentFlight = null;
      if (this.el.telemetryDrawer) {
        this.el.telemetryDrawer.classList.remove('open');
      }
      if (window.AeroMarkers) {
        window.AeroMarkers.clearSelection();
      }
      if (window.AeroMap) {
        setTimeout(() => window.AeroMap.invalidateSize(), 300);
      }
    }

    _toCardinal(deg) {
      const cardinals = ['NORTH', 'NNE', 'NE', 'ENE', 'EAST', 'ESE', 'SE', 'SSE', 'SOUTH', 'SSW', 'SW', 'WSW', 'WEST', 'WNW', 'NW', 'NNW'];
      const idx = Math.round((deg % 360) / 22.5) % 16;
      return cardinals[idx];
    }

    /**
     * Updates and renders the aircraft data table overlay
     * @param {Object[]} aircraftList
     */
    updateTableData(aircraftList) {
      this.tableData = Array.isArray(aircraftList) ? aircraftList : [];

      // Update pill counts
      const totalAll = this.tableData.length;
      const totalNominal = this.tableData.filter(f => !f.has_anomaly && f.status === 'NOMINAL').length;
      const totalAnomalies = this.tableData.filter(f => f.has_anomaly || f.status !== 'NOMINAL').length;

      if (this.el.pillCountAll) this.el.pillCountAll.textContent = totalAll;
      if (this.el.pillCountNominal) this.el.pillCountNominal.textContent = totalNominal;
      if (this.el.pillCountAnomalies) this.el.pillCountAnomalies.textContent = totalAnomalies;

      if (this.isTableOpen) {
        this.renderTable();
      }
    }

    setTableFilter(filter) {
      this.tableFilter = filter;
      [this.el.filterAll, this.el.filterNominal, this.el.filterAnomalies].forEach(pill => {
        if (!pill) return;
        if (pill.dataset.filter === filter) pill.classList.add('active');
        else pill.classList.remove('active');
      });
      this.renderTable();
    }

    toggleTable() {
      if (this.isTableOpen) {
        this.closeTable();
      } else {
        this.openTable();
      }
    }

    openTable() {
      this.isTableOpen = true;
      if (this.el.aircraftTableOverlay) {
        this.el.aircraftTableOverlay.classList.add('open');
      }
      if (this.el.tableToggleBtn) {
        this.el.tableToggleBtn.classList.add('active');
      }
      this.renderTable();
      if (window.AeroMap) {
        setTimeout(() => window.AeroMap.invalidateSize(), 350);
      }
    }

    closeTable() {
      this.isTableOpen = false;
      if (this.el.aircraftTableOverlay) {
        this.el.aircraftTableOverlay.classList.remove('open');
      }
      if (this.el.tableToggleBtn) {
        this.el.tableToggleBtn.classList.remove('active');
      }
      if (window.AeroMap) {
        setTimeout(() => window.AeroMap.invalidateSize(), 350);
      }
    }

    _updateSortHeaders() {
      if (!this.el.aircraftTable) return;
      const headers = this.el.aircraftTable.querySelectorAll('th[data-col]');
      headers.forEach(th => {
        const arrow = th.querySelector('.sort-arrow');
        if (arrow) {
          if (th.dataset.col === this.sortCol) {
            arrow.textContent = this.sortAsc ? '▲' : '▼';
            arrow.style.color = 'var(--hud-cyan)';
          } else {
            arrow.textContent = '';
          }
        }
      });
    }

    renderTable() {
      if (!this.el.aircraftTableBody) return;

      // 1. Filter by status
      let filtered = this.tableData.filter(f => {
        const isAnom = Boolean(f.has_anomaly || (f.status && f.status !== 'NOMINAL'));
        if (this.tableFilter === 'NOMINAL') return !isAnom;
        if (this.tableFilter === 'ANOMALIES') return isAnom;
        return true;
      });

      // 2. Filter by search query (safe case-insensitive string search)
      if (this.tableSearch) {
        const q = this.tableSearch.toLowerCase();
        filtered = filtered.filter(f => {
          const callsign = (f.callsign || '').toLowerCase();
          const icao = (f.icao24 || '').toLowerCase();
          const country = (f.origin_country || '').toLowerCase();
          return callsign.includes(q) || icao.includes(q) || country.includes(q);
        });
      }

      // 3. Sort (with nulls sorted to bottom in both directions)
      const col = this.sortCol;
      const asc = this.sortAsc;

      filtered.sort((a, b) => {
        let valA = a[col];
        let valB = b[col];

        // Derived numeric fields for sorting
        if (col === 'baro_altitude') {
          valA = a.alt_ft ?? a.baro_altitude;
          valB = b.alt_ft ?? b.baro_altitude;
        } else if (col === 'velocity') {
          valA = a.speed_kts ?? a.velocity;
          valB = b.speed_kts ?? b.velocity;
        } else if (col === 'vertical_rate') {
          valA = a.climb_fpm ?? a.vertical_rate;
          valB = b.climb_fpm ?? b.vertical_rate;
        }

        // Nulls always to bottom
        if (valA === null || valA === undefined) return 1;
        if (valB === null || valB === undefined) return -1;

        if (typeof valA === 'string') {
          return asc ? valA.localeCompare(valB) : valB.localeCompare(valA);
        }
        return asc ? (valA - valB) : (valB - valA);
      });

      if (filtered.length === 0) {
        this.el.aircraftTableBody.innerHTML = `
          <tr><td colspan="9" style="text-align: center; color: var(--hud-text-dim); padding: 24px;">NO MATCHING FLIGHT VECTORS FOUND</td></tr>
        `;
        return;
      }

      let html = '';
      filtered.forEach(f => {
        const isAnom = Boolean(f.has_anomaly || (f.status && f.status !== 'NOMINAL'));
        const callsign = f.callsign || f.icao24?.toUpperCase() || 'UNKNOWN';
        const icao = (f.icao24 || '------').toUpperCase();
        const country = f.origin_country || 'UNKNOWN';

        const altFt = f.alt_ft ?? (typeof f.baro_altitude === 'number' ? Math.round(f.baro_altitude * 3.28084) : null);
        const altStr = altFt !== null ? `${altFt.toLocaleString()} ft` : '---';

        const speedKts = f.speed_kts ?? (typeof f.velocity === 'number' ? Math.round(f.velocity * 1.943844) : null);
        const speedStr = speedKts !== null ? `${speedKts.toLocaleString()} kts` : '---';

        const climbFpm = f.climb_fpm ?? (typeof f.vertical_rate === 'number' ? Math.round(f.vertical_rate * 196.85) : null);
        const climbStr = climbFpm !== null ? `${climbFpm > 0 ? '+' : ''}${climbFpm.toLocaleString()}` : '---';

        const squawk = f.squawk || '----';
        const status = (f.status || 'NOMINAL').toUpperCase();
        const sevClass = isAnom ? `badge-${status.toLowerCase()}` : 'badge-nominal';

        html += `
          <tr class="${isAnom ? 'anomalous-row' : ''}" data-icao="${(f.icao24 || '').toLowerCase()}">
            <td style="font-weight: bold; color: ${isAnom ? 'var(--hud-crimson)' : 'var(--hud-cyan)'};">${callsign}</td>
            <td>${icao}</td>
            <td>${country}</td>
            <td>${altStr}</td>
            <td>${speedStr}</td>
            <td>${climbStr}</td>
            <td style="${['7500','7600','7700'].includes(squawk) ? 'color: var(--hud-crimson); font-weight: bold;' : ''}">${squawk}</td>
            <td><span class="badge ${sevClass}">${status}</span></td>
            <td><button class="hud-btn table-inspect-btn" style="padding: 2px 6px; font-size: 10px;">INSPECT</button></td>
          </tr>
        `;
      });

      this.el.aircraftTableBody.innerHTML = html;

      // Row click listener to open drawer & focus aircraft
      this.el.aircraftTableBody.querySelectorAll('tr[data-icao]').forEach(row => {
        row.addEventListener('click', () => {
          const icao = row.dataset.icao;
          if (icao && window.AeroMarkers) {
            const flight = window.AeroMarkers.getAircraft(icao);
            if (flight) {
              if (window.AeroMap && typeof flight.latitude === 'number' && typeof flight.longitude === 'number') {
                window.AeroMap.flyToFlight(flight.latitude, flight.longitude, 9);
              }
              window.AeroMarkers.selectAircraft(icao);
              this.openDrawer(flight);
            }
          }
        });
      });
    }
  }

  window.AeroPanels = new TacticalPanelsManager();
})(window);
