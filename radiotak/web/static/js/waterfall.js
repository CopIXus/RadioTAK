/* Canvas waterfall for spectrum frames over WebSocket */
(function (global) {
  'use strict';

  function Waterfall(canvas, opts) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.bins = opts && opts.bins || 512;
    this.history = [];
    this.maxRows = opts && opts.maxRows || 120;
    this.ccMarkersHz = (opts && opts.ccMarkersHz) || [];
    this.fMin = opts && opts.fMin || 0;
    this.fMax = opts && opts.fMax || 0;
    this.emptyText = (opts && opts.emptyText) || 'Waiting for spectrum frames…';
    this._resize();
    this.draw();
  }

  Waterfall.prototype._resize = function () {
    var dpr = window.devicePixelRatio || 1;
    var w = this.canvas.clientWidth || 600;
    var h = this.canvas.clientHeight || 180;
    this.canvas.width = Math.floor(w * dpr);
    this.canvas.height = Math.floor(h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.w = w;
    this.h = h;
  };

  Waterfall.prototype.pushFrame = function (frame) {
    if (!frame) return;
    var bins = frame.bins || frame.magnitudes || frame.data;
    if (!bins || !bins.length) return;
    if (frame.f_min != null) this.fMin = frame.f_min;
    if (frame.f_max != null) this.fMax = frame.f_max;
    if (frame.cc_hz) this.ccMarkersHz = frame.cc_hz;
    this.history.unshift(bins);
    if (this.history.length > this.maxRows) this.history.pop();
    this.draw();
    this.applyAxis(frame);
  };

  Waterfall.prototype.setAxisElements = function (els) {
    this._axis = els || null;
    return this;
  };

  Waterfall.prototype.applyAxis = function (frame) {
    var els = this._axis;
    if (!els || !frame || frame.f_min == null || frame.f_max == null) return;
    if (els.fmin) els.fmin.textContent = (frame.f_min / 1e6).toFixed(3) + ' MHz';
    if (els.fmax) els.fmax.textContent = (frame.f_max / 1e6).toFixed(3) + ' MHz';
    if (!els.note) return;
    var ccs = frame.cc_hz || this.ccMarkersHz || [];
    var outside = ccs.length && frame.f_max > frame.f_min && ccs.every(function (hz) {
      return hz < frame.f_min || hz > frame.f_max;
    });
    if (outside) {
      els.note.hidden = false;
      els.note.textContent = 'This canvas is the tuner window, not your control channels. '
        + 'Save the system (or press Start) so SDRTrunk retunes the stick off its 101.1 MHz default.';
    } else {
      els.note.hidden = true;
      els.note.textContent = '';
    }
  };

  Waterfall.prototype._color = function (v) {
    // v expected 0..1
    var t = Math.max(0, Math.min(1, v));
    var r = Math.floor(20 + t * 200);
    var g = Math.floor(30 + t * 120);
    var b = Math.floor(80 + (1 - t) * 100);
    return 'rgb(' + r + ',' + g + ',' + b + ')';
  };

  Waterfall.prototype.draw = function () {
    var ctx = this.ctx;
    var w = this.w;
    var h = this.h;
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, w, h);
    if (!this.history.length) {
      ctx.fillStyle = '#64748b';
      ctx.font = '12px JetBrains Mono, monospace';
      ctx.fillText(this.emptyText, 12, 24);
      return;
    }
    var rowH = Math.max(1, h / this.maxRows);
    for (var y = 0; y < this.history.length; y++) {
      var row = this.history[y];
      var n = row.length;
      var cellW = w / n;
      var max = 1e-9;
      for (var i = 0; i < n; i++) if (row[i] > max) max = row[i];
      for (var x = 0; x < n; x++) {
        ctx.fillStyle = this._color(row[x] / max);
        ctx.fillRect(x * cellW, y * rowH, cellW + 0.5, rowH + 0.5);
      }
    }
    // control-channel markers
    if (this.fMax > this.fMin && this.ccMarkersHz && this.ccMarkersHz.length) {
      ctx.strokeStyle = 'rgba(6,182,212,.85)';
      ctx.lineWidth = 1;
      this.ccMarkersHz.forEach(function (hz) {
        var t = (hz - this.fMin) / (this.fMax - this.fMin);
        if (t < 0 || t > 1) return;
        var x = t * w;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
      }.bind(this));
    }
  };

  Waterfall.prototype.connect = function (url) {
    var self = this;
    var ws;
    var retry = 1000;
    function open() {
      ws = new WebSocket(url);
      ws.binaryType = 'arraybuffer';
      ws.onopen = function () {
        retry = 1000;
        if (self.onStatus) self.onStatus('live');
      };
      ws.onclose = function () {
        if (self.onStatus) self.onStatus('dead');
        setTimeout(open, retry);
        retry = Math.min(retry * 1.5, 15000);
      };
      ws.onmessage = function (ev) {
        try {
          var frame = typeof ev.data === 'string' ? JSON.parse(ev.data) : null;
          if (frame) self.pushFrame(frame);
        } catch (e) { /* ignore */ }
      };
    }
    open();
    window.addEventListener('resize', function () { self._resize(); self.draw(); });
    return this;
  };

  global.RadioTakWaterfall = Waterfall;
})(window);
