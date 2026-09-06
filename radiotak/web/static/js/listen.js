/* Browser playback of decoded talkgroup PCM from /api/v1/ws/audio */
(function (global) {
  'use strict';

  function decodePcmS16Le(b64) {
    if (!b64) return new Int16Array(0);
    var bin = atob(b64);
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    if (bytes.byteLength < 2) return new Int16Array(0);
    return new Int16Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.byteLength / 2));
  }

  function resampleTo(int16, fromRate, toRate) {
    var nSrc = int16.length;
    if (!nSrc) return new Float32Array(0);
    if (fromRate === toRate) {
      var direct = new Float32Array(nSrc);
      for (var i = 0; i < nSrc; i++) direct[i] = int16[i] / 32768;
      return direct;
    }
    var ratio = toRate / fromRate;
    var n = Math.max(1, Math.floor(nSrc * ratio));
    var out = new Float32Array(n);
    var last = nSrc - 1;
    for (var o = 0; o < n; o++) {
      var src = o / ratio;
      var i0 = Math.min(last, Math.floor(src));
      var i1 = Math.min(last, i0 + 1);
      var f = src - i0;
      var s0 = int16[i0] / 32768;
      var s1 = int16[i1] / 32768;
      out[o] = s0 + (s1 - s0) * f;
    }
    return out;
  }

  function callLabel(frame) {
    var tg = frame && frame.talkgroup;
    var rid = frame && frame.radio_id;
    var parts = [];
    if (tg) parts.push('TG ' + tg);
    if (rid) parts.push('radio ' + rid);
    return parts.join(' · ');
  }

  function Listen(root, opts) {
    this.root = root;
    this.btn = root.querySelector('[data-listen-toggle]');
    this.statusEl = root.querySelector('[data-listen-status]');
    this.url = (opts && opts.url) || '';
    this.playing = false;
    this.ctx = null;
    this.ws = null;
    this.nextTime = 0;
    this._retry = 1000;
    var self = this;
    if (this.btn) {
      this.btn.addEventListener('click', function () {
        if (self.playing) self.stop();
        else self.start();
      });
    }
    this.setStatus('Click Listen to hear decoded talkgroups in this browser.');
  }

  Listen.prototype.setStatus = function (text, kind) {
    if (!this.statusEl) return;
    this.statusEl.textContent = text;
    this.statusEl.classList.remove('live', 'encrypted', 'idle');
    this.statusEl.classList.add(kind || 'idle');
  };

  Listen.prototype.setPlayingUi = function (on) {
    this.playing = on;
    if (this.btn) {
      this.btn.textContent = on ? 'Stop listening' : 'Listen in browser';
      this.btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      this.btn.classList.toggle('btn-listen-active', on);
      this.btn.classList.toggle('btn-primary', !on);
    }
    if (this.root) this.root.classList.toggle('is-listening', on);
  };

  Listen.prototype.start = function () {
    var self = this;
    var AC = global.AudioContext || global.webkitAudioContext;
    if (!AC) {
      this.setStatus('This browser cannot play live audio.', 'encrypted');
      return;
    }
    this.ctx = new AC();
    var unlock = this.ctx.resume && this.ctx.resume();
    Promise.resolve(unlock).then(function () {
      self.nextTime = 0;
      self.setPlayingUi(true);
      self.setStatus('Connecting to decoder audio…', 'idle');
      self._open();
    }).catch(function () {
      self.setStatus('Click Listen again after allowing audio.', 'encrypted');
      self.setPlayingUi(false);
    });
  };

  Listen.prototype.stop = function () {
    this.setPlayingUi(false);
    this._retry = 1000;
    if (this.ws) {
      var ws = this.ws;
      this.ws = null;
      try { ws.close(); } catch (e) { /* ignore */ }
    }
    if (this.ctx) {
      try { this.ctx.close(); } catch (e) { /* ignore */ }
      this.ctx = null;
    }
    this.setStatus('Stopped. Click Listen to hear decoded talkgroups.');
  };

  Listen.prototype._open = function () {
    var self = this;
    if (!this.playing) return;
    var ws;
    try {
      ws = new WebSocket(this.url);
    } catch (e) {
      this.setStatus('Could not open audio stream.', 'encrypted');
      return;
    }
    this.ws = ws;
    ws.onopen = function () {
      self._retry = 1000;
      self.setStatus('Waiting for a talkgroup…', 'idle');
    };
    ws.onclose = function () {
      if (!self.playing || self.ws !== ws) return;
      self.setStatus('Audio stream dropped — retrying…', 'idle');
      setTimeout(function () { self._open(); }, self._retry);
      self._retry = Math.min(self._retry * 1.5, 15000);
    };
    ws.onmessage = function (ev) {
      try {
        var frame = typeof ev.data === 'string' ? JSON.parse(ev.data) : null;
        if (frame) self._onFrame(frame);
      } catch (e) { /* ignore */ }
    };
  };

  Listen.prototype._onFrame = function (frame) {
    if (!this.playing) return;
    var label = callLabel(frame);
    if (frame.encrypted) {
      this.setStatus(
        'Encrypted — silence' + (label ? ' (' + label + ')' : ''),
        'encrypted'
      );
      return;
    }
    if (frame.end && !frame.pcm_b64) {
      this.setStatus(label ? 'Call ended · ' + label : 'Waiting for a talkgroup…', 'idle');
      return;
    }
    if (!frame.pcm_b64) {
      if (label) this.setStatus('Waiting for voice · ' + label, 'idle');
      return;
    }
    this._playPcm(frame);
    this.setStatus(label ? 'Live · ' + label : 'Live talkgroup audio', 'live');
  };

  Listen.prototype._playPcm = function (frame) {
    if (!this.ctx) return;
    var int16 = decodePcmS16Le(frame.pcm_b64);
    if (!int16.length) return;
    var fromRate = frame.sample_rate || 8000;
    var toRate = this.ctx.sampleRate || fromRate;
    var samples = resampleTo(int16, fromRate, toRate);
    if (!samples.length) return;
    var buf = this.ctx.createBuffer(1, samples.length, toRate);
    buf.getChannelData(0).set(samples);
    var src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(this.ctx.destination);
    var now = this.ctx.currentTime;
    if (this.nextTime < now - 0.25) this.nextTime = now;
    var startAt = Math.max(now, this.nextTime);
    src.start(startAt);
    this.nextTime = startAt + buf.duration;
  };

  Listen.mount = function (root, opts) {
    if (!root) return null;
    return new Listen(root, opts || {});
  };

  global.RadioTakListen = Listen;
})(window);
