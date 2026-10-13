/**
 * AeroPulse Dual-Mode Network Client
 * static/js/network.js - WebSocket live streaming with resilient HTTP polling fallback
 * and exponential backoff reconnection watchdog.
 */

(function(window) {
  'use strict';

  class TacticalNetworkAdapter {
    constructor() {
      this.ws = null;
      this.wsUrl = null;
      this.mode = 'DISCONNECTED'; // 'WS' | 'POLLING' | 'RECONNECTING' | 'DISCONNECTED'
      this.isPolling = false;
      this.pollingTimer = null;
      this.pollingIntervalMs = 3500; // 3.5s update cadence
      this.reconnectAttempts = 0;
      this.reconnectTimer = null;
      this.pingTimer = null;

      // Subscribers
      this.onTelemetryCallback = null;
      this.onAnomaliesCallback = null;
      this.onConnectionChangeCallback = null;
    }

    /**
     * Initializes network adapter with event listeners
     */
    init(config = {}) {
      this.onTelemetryCallback = config.onTelemetry || null;
      this.onAnomaliesCallback = config.onAnomalies || null;
      this.onConnectionChangeCallback = config.onConnectionChange || null;

      // Determine WebSocket protocol (ws: or wss:)
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host || 'localhost:8000';
      this.wsUrl = `${protocol}//${host}/ws/telemetry`;

      // Start primary connection
      this.connectWebSocket();

      // Initial anomalies fetch
      this.fetchAnomalies();
    }

    _setMode(newMode) {
      if (this.mode !== newMode) {
        this.mode = newMode;
        if (this.onConnectionChangeCallback) {
          this.onConnectionChangeCallback(newMode);
        }
      }
    }

    /**
     * Attempts WebSocket connection
     */
    connectWebSocket() {
      if (this.ws && (this.ws.readyState === WebSocket.CONNECTING || this.ws.readyState === WebSocket.OPEN)) {
        return;
      }

      this._clearReconnectTimer();

      try {
        this.ws = new WebSocket(this.wsUrl);
      } catch (err) {
        this._handleWebSocketFailure();
        return;
      }

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.stopPolling();
        this._setMode('WS');
        this._startPingKeepalive();
      };

      this.ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          const eventType = (payload.event || payload.type || '').toUpperCase();

          if (eventType === 'SNAPSHOT' || eventType === 'UPDATE') {
            const telemetryData = payload.data || payload;
            if (this.onTelemetryCallback) {
              this.onTelemetryCallback(telemetryData, 'WS');
            }
          } else if (eventType === 'PONG') {
            // Heartbeat response acknowledged
          }
        } catch (parseErr) {
          // Ignore parse errors on malformed messages
        }
      };

      this.ws.onerror = () => {
        // Triggers onclose next
      };

      this.ws.onclose = () => {
        this._stopPingKeepalive();
        this._handleWebSocketFailure();
      };
    }

    _handleWebSocketFailure() {
      this._setMode('POLLING');
      this.startPolling();
      this._scheduleReconnect();
    }

    _scheduleReconnect() {
      if (this.reconnectTimer) return;

      // Exponential backoff: min(2^attempts * 1500, 15000) ms
      const delay = Math.min(Math.pow(2, this.reconnectAttempts) * 1500, 15000);
      this.reconnectAttempts++;

      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null;
        this._setMode('RECONNECTING');
        this.connectWebSocket();
      }, delay);
    }

    _clearReconnectTimer() {
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
      }
    }

    _startPingKeepalive() {
      this._stopPingKeepalive();
      this.pingTimer = setInterval(() => {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ type: 'PING' }));
        }
      }, 10000); // Send PING every 10s
    }

    _stopPingKeepalive() {
      if (this.pingTimer) {
        clearInterval(this.pingTimer);
        this.pingTimer = null;
      }
    }

    /**
     * Fallback HTTP Polling Engine
     */
    startPolling() {
      if (this.isPolling) return;
      this.isPolling = true;

      // Execute immediate poll
      this.fetchTelemetry();
      this.fetchAnomalies();

      // Schedule periodic polling
      this.pollingTimer = setInterval(() => {
        this.fetchTelemetry();
        this.fetchAnomalies();
      }, this.pollingIntervalMs);
    }

    stopPolling() {
      if (!this.isPolling) return;
      this.isPolling = false;
      if (this.pollingTimer) {
        clearInterval(this.pollingTimer);
        this.pollingTimer = null;
      }
    }

    /**
     * Queries GET /api/telemetry
     */
    async fetchTelemetry() {
      try {
        const res = await fetch('/api/telemetry');
        if (res.ok) {
          const data = await res.json();
          if (this.onTelemetryCallback) {
            this.onTelemetryCallback(data, this.mode);
          }
        }
      } catch (err) {
        // Polling error silently handled
      }
    }

    /**
     * Queries GET /api/anomalies
     */
    async fetchAnomalies() {
      try {
        const res = await fetch('/api/anomalies?limit=50');
        if (res.ok) {
          const data = await res.json();
          const list = Array.isArray(data) ? data : (data.events || data.anomalies || []);
          if (this.onAnomaliesCallback) {
            this.onAnomaliesCallback(list);
          }
        }
      } catch (err) {
        // Anomalies fetch error silently handled
      }
    }
  }

  window.AeroNetwork = new TacticalNetworkAdapter();
})(window);
