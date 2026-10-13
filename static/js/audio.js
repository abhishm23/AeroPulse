/**
 * AeroPulse Tactical Audio Synthesizer
 * static/js/audio.js - Web Audio API procedural tactical sound effects
 * Zero external audio assets. Synthetic military radar chirps and emergency klaxons.
 */

(function(window) {
  'use strict';

  class TacticalAudioEngine {
    constructor() {
      this.ctx = null;
      this.isAudioUnlocked = false;
      this.muted = localStorage.getItem('aeropulse_audio_muted') === 'true';
      this.lastPlayTimestamp = 0;
      this.cooldownMs = 1200; // Debounce guard to prevent audio clipping

      // Bind first user interaction to resume AudioContext
      this._bindAutoplayUnlock();
    }

    _getAudioContext() {
      if (!this.ctx) {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (AudioCtx) {
          this.ctx = new AudioCtx();
        }
      }
      return this.ctx;
    }

    _bindAutoplayUnlock() {
      const unlockEvents = ['pointerdown', 'keydown', 'click'];
      const unlockHandler = () => {
        const ctx = this._getAudioContext();
        if (ctx && ctx.state === 'suspended') {
          ctx.resume().then(() => {
            this.isAudioUnlocked = true;
          }).catch(() => {});
        } else if (ctx && ctx.state === 'running') {
          this.isAudioUnlocked = true;
        }
        unlockEvents.forEach(evt => window.removeEventListener(evt, unlockHandler));
      };

      unlockEvents.forEach(evt => window.addEventListener(evt, unlockHandler, { once: true, passive: true }));
    }

    isMuted() {
      return this.muted;
    }

    setMuted(muted) {
      this.muted = Boolean(muted);
      localStorage.setItem('aeropulse_audio_muted', this.muted ? 'true' : 'false');
      return this.muted;
    }

    toggleMute() {
      return this.setMuted(!this.muted);
    }

    /**
     * Tactical Radar Anomaly Chirp (880Hz decaying to 440Hz sine wave)
     */
    playRadarChirp() {
      if (this.muted) return;
      const nowMs = Date.now();
      if (nowMs - this.lastPlayTimestamp < this.cooldownMs) return;
      this.lastPlayTimestamp = nowMs;

      try {
        const ctx = this._getAudioContext();
        if (!ctx || ctx.state !== 'running') return;

        const now = ctx.currentTime;
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();

        osc.type = 'sine';
        osc.frequency.setValueAtTime(880, now); // A5 note
        osc.frequency.exponentialRampToValueAtTime(440, now + 0.32);

        gain.gain.setValueAtTime(0.25, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.32);

        osc.connect(gain);
        gain.connect(ctx.destination);

        osc.start(now);
        osc.stop(now + 0.33);
      } catch (err) {
        // Silently ignore audio playback errors
      }
    }

    /**
     * Emergency Klaxon Warble (Dual-tone 800Hz / 1000Hz alternating alarm)
     */
    playKlaxonAlarm() {
      if (this.muted) return;
      const nowMs = Date.now();
      if (nowMs - this.lastPlayTimestamp < this.cooldownMs) return;
      this.lastPlayTimestamp = nowMs;

      try {
        const ctx = this._getAudioContext();
        if (!ctx || ctx.state !== 'running') return;

        const now = ctx.currentTime;
        const duration = 0.55;

        // Two alternating pulses
        const osc1 = ctx.createOscillator();
        const osc2 = ctx.createOscillator();
        const gain = ctx.createGain();

        osc1.type = 'sawtooth';
        osc1.frequency.setValueAtTime(780, now);
        osc1.frequency.linearRampToValueAtTime(1020, now + 0.25);
        osc1.frequency.linearRampToValueAtTime(780, now + 0.50);

        osc2.type = 'square';
        osc2.frequency.setValueAtTime(390, now);
        osc2.frequency.linearRampToValueAtTime(510, now + 0.25);
        osc2.frequency.linearRampToValueAtTime(390, now + 0.50);

        gain.gain.setValueAtTime(0.18, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + duration);

        osc1.connect(gain);
        osc2.connect(gain);
        gain.connect(ctx.destination);

        osc1.start(now);
        osc2.start(now);
        osc1.stop(now + duration);
        osc2.stop(now + duration);
      } catch (err) {
        // Silently ignore audio errors
      }
    }

    /**
     * Dispatches appropriate alert based on anomaly severity
     * @param {string} severity - 'CRITICAL' | 'SEVERE' | 'WARNING'
     */
    playAnomalyAlert(severity) {
      const sev = (severity || '').toUpperCase();
      if (sev === 'CRITICAL' || sev === 'SEVERE') {
        this.playKlaxonAlarm();
      } else {
        this.playRadarChirp();
      }
    }
  }

  window.AeroAudio = new TacticalAudioEngine();
})(window);
