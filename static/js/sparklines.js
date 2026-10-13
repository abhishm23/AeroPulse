/**
 * AeroPulse HTML5 Canvas Sparklines Engine
 * static/js/sparklines.js - Pure HTML5 Canvas 2D mini-charts
 * Renders smooth kinematic altitude and velocity trends with neon glow & Retina DPI scaling.
 */

(function(window) {
  'use strict';

  class TacticalSparklineRenderer {
    /**
     * Prepares canvas for crisp high-DPI / Retina rendering
     */
    _setupCanvas(canvas) {
      if (!canvas) return null;
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      const displayWidth = rect.width > 0 ? rect.width : (canvas.width || 340);
      const displayHeight = rect.height > 0 ? rect.height : (canvas.height || 70);

      // Only resize if internal dimensions do not match
      if (canvas.width !== Math.round(displayWidth * dpr) || canvas.height !== Math.round(displayHeight * dpr)) {
        canvas.width = Math.round(displayWidth * dpr);
        canvas.height = Math.round(displayHeight * dpr);
      }

      const ctx = canvas.getContext('2d');
      ctx.setTransform(1, 0, 0, 1, 0, 0); // Reset transform
      ctx.scale(dpr, dpr);
      return { ctx, width: displayWidth, height: displayHeight };
    }

    /**
     * Draws fallback baseline when history is insufficient (< 2 points)
     */
    _renderBufferingState(ctx, width, height, strokeColor, label = 'BUFFERING KINEMATIC HISTORY...') {
      ctx.clearRect(0, 0, width, height);

      // Dashed baseline
      ctx.save();
      ctx.strokeStyle = strokeColor || '#00f3ff';
      ctx.globalAlpha = 0.3;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(10, height / 2);
      ctx.lineTo(width - 10, height / 2);
      ctx.stroke();

      // Text label
      ctx.font = '10px "JetBrains Mono", monospace';
      ctx.fillStyle = '#94a3b8';
      ctx.globalAlpha = 0.6;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(label, width / 2, height / 2 - 10);
      ctx.restore();
    }

    /**
     * Core line chart renderer
     * @param {HTMLCanvasElement} canvas
     * @param {number[]} values
     * @param {Object} options
     */
    drawSparkline(canvas, values, options = {}) {
      const setup = this._setupCanvas(canvas);
      if (!setup) return;
      const { ctx, width, height } = setup;

      const strokeColor = options.strokeColor || '#00f3ff';
      const glowColor = options.glowColor || 'rgba(0, 243, 255, 0.5)';
      const unit = options.unit || '';

      // Filter valid numbers
      const cleanData = (values || []).filter(v => typeof v === 'number' && !isNaN(v) && isFinite(v));

      if (cleanData.length < 2) {
        this._renderBufferingState(ctx, width, height, strokeColor);
        return;
      }

      ctx.clearRect(0, 0, width, height);

      // Dimensions with padding for text labels
      const padTop = 16;
      const padBottom = 16;
      const padLeft = 8;
      const padRight = 8;
      const chartWidth = width - padLeft - padRight;
      const chartHeight = height - padTop - padBottom;

      let min = Math.min(...cleanData);
      let max = Math.max(...cleanData);

      // Prevent divide by zero if flat
      if (max === min) {
        min -= 1;
        max += 1;
      }

      const range = max - min;
      const stepX = chartWidth / (cleanData.length - 1);

      // Coordinates mapping
      const points = cleanData.map((val, idx) => {
        const x = padLeft + idx * stepX;
        const normY = (val - min) / range;
        const y = padTop + chartHeight - (normY * chartHeight);
        return { x, y, val };
      });

      // 1. Draw gradient fill underneath
      ctx.save();
      const grad = ctx.createLinearGradient(0, padTop, 0, height);
      grad.addColorStop(0, glowColor);
      grad.addColorStop(1, 'rgba(5, 8, 17, 0)');

      ctx.beginPath();
      ctx.moveTo(points[0].x, height - padBottom);
      ctx.lineTo(points[0].x, points[0].y);
      for (let i = 1; i < points.length; i++) {
        ctx.lineTo(points[i].x, points[i].y);
      }
      ctx.lineTo(points[points.length - 1].x, height - padBottom);
      ctx.closePath();
      ctx.fillStyle = grad;
      ctx.fill();
      ctx.restore();

      // 2. Draw glowing neon path
      ctx.save();
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 2;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.shadowColor = strokeColor;
      ctx.shadowBlur = 6;

      ctx.beginPath();
      ctx.moveTo(points[0].x, points[0].y);
      for (let i = 1; i < points.length; i++) {
        ctx.lineTo(points[i].x, points[i].y);
      }
      ctx.stroke();
      ctx.restore();

      // 3. Draw head pulse dot on newest point
      const lastPoint = points[points.length - 1];
      ctx.save();
      ctx.fillStyle = '#ffffff';
      ctx.shadowColor = strokeColor;
      ctx.shadowBlur = 8;
      ctx.beginPath();
      ctx.arc(lastPoint.x, lastPoint.y, 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      // 4. Draw min & max text labels
      ctx.save();
      ctx.font = '9px "JetBrains Mono", monospace';
      ctx.fillStyle = '#94a3b8';
      ctx.textBaseline = 'top';
      ctx.textAlign = 'left';
      ctx.fillText(`MAX: ${Math.round(max).toLocaleString()}${unit}`, padLeft, 2);

      ctx.textBaseline = 'bottom';
      ctx.fillText(`MIN: ${Math.round(min).toLocaleString()}${unit}`, padLeft, height - 2);
      ctx.restore();
    }

    /**
     * Renders altitude trend (converted to feet)
     * @param {HTMLCanvasElement} canvas
     * @param {Object[]} trail - Array of TrailPoint objects or numbers
     */
    renderAltitude(canvas, trail) {
      if (!trail || !canvas) return;
      const values = trail.map(pt => {
        if (typeof pt === 'number') return pt;
        if (pt && typeof pt.alt_ft === 'number') return pt.alt_ft;
        if (pt && typeof pt.altitude === 'number') return pt.altitude * 3.28084;
        return null;
      });

      this.drawSparkline(canvas, values, {
        strokeColor: '#00f3ff',
        glowColor: 'rgba(0, 243, 255, 0.35)',
        unit: ' ft'
      });
    }

    /**
     * Renders ground speed trend (converted to knots)
     * @param {HTMLCanvasElement} canvas
     * @param {Object[]} trail - Array of TrailPoint objects or numbers
     * @param {boolean} isOverspeed - Whether overspeed trap is flagged
     */
    renderSpeed(canvas, trail, isOverspeed = false) {
      if (!trail || !canvas) return;
      const values = trail.map(pt => {
        if (typeof pt === 'number') return pt;
        if (pt && typeof pt.speed_kts === 'number') return pt.speed_kts;
        if (pt && typeof pt.velocity === 'number') return pt.velocity * 1.943844;
        return null;
      });

      const strokeColor = isOverspeed ? '#ff003c' : '#ffb700';
      const glowColor = isOverspeed ? 'rgba(255, 0, 60, 0.4)' : 'rgba(255, 183, 0, 0.35)';

      this.drawSparkline(canvas, values, {
        strokeColor,
        glowColor,
        unit: ' kts'
      });
    }
  }

  window.AeroSparklines = new TacticalSparklineRenderer();
})(window);
