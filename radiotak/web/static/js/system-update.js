/* Live System → Update overlay: stream log, survive console restart. */
(function () {
  'use strict';

  var KEY = 'radiotak_update';
  var overlay, term, title, sub, hint;
  var pollTimer = null;
  var lastLog = '';
  var offlineSince = 0;
  var finishing = false;

  function $(id) { return document.getElementById(id); }

  function store(obj) {
    try { localStorage.setItem(KEY, JSON.stringify(obj)); } catch (e) { /* quota / private */ }
  }
  function loadStore() {
    try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) { return null; }
  }
  function clearStore() {
    try { localStorage.removeItem(KEY); } catch (e) { /* ignore */ }
  }

  function pingSw(type) {
    if (!navigator.serviceWorker || !navigator.serviceWorker.controller) return;
    try { navigator.serviceWorker.controller.postMessage({ type: type }); } catch (e) { /* ignore */ }
  }

  function showOverlay() {
    if (!overlay) return;
    overlay.hidden = false;
    overlay.removeAttribute('hidden');
  }

  function setPhase(phase) {
    if (!overlay) return;
    overlay.classList.remove('is-offline', 'is-done', 'is-failed');
    if (phase) overlay.classList.add('is-' + phase);
  }

  function setLog(text) {
    lastLog = text || '';
    if (term) {
      term.textContent = lastLog;
      term.scrollTop = term.scrollHeight;
    }
    var st = loadStore() || { active: true };
    st.log = lastLog;
    st.active = true;
    store(st);
  }

  function begin() {
    var prev = loadStore() || {};
    store({ active: true, log: prev.log || lastLog, started: prev.started || Date.now() });
    pingSw('radiotak-updating');
    showOverlay();
    if (title) title.textContent = 'Update in progress';
    if (sub) {
      sub.textContent = 'RadioTAK is pulling a new build. The console will restart and this page will wait until it comes back.';
    }
    if (hint) hint.textContent = 'Keep this tab open. Do not power-cycle the Pi.';
    setPhase('');
    startPoll();
  }

  function startPoll() {
    if (pollTimer) return;
    tick();
    pollTimer = setInterval(tick, 800);
  }

  function stopPoll() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function tick() {
    fetch('/api/v1/system/update', { credentials: 'same-origin' })
      .then(function (r) {
        var ct = r.headers.get('content-type') || '';
        if (!r.ok || ct.indexOf('json') === -1) throw new Error('status ' + r.status);
        return r.json();
      })
      .then(onStatus)
      .catch(function () {
        fetch('/api/v1/health', { credentials: 'same-origin' })
          .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
          .then(onHealth)
          .catch(onOffline);
      });
  }

  function onStatus(data) {
    offlineSince = 0;
    var u = (data && data.update) || {};
    if (u.log) setLog(u.log);
    var st = u.state || 'idle';
    if (st === 'running') {
      if (title) title.textContent = 'Update in progress';
      setPhase('');
    } else if (st === 'restarting') {
      if (title) title.textContent = 'Console is restarting';
      if (sub) {
        sub.textContent = 'RadioTAK is coming back online. This screen will stay up until the console responds.';
      }
      setPhase('offline');
    } else if (st === 'done') {
      finishOk(u.to_version || (data && data.installed));
    } else if (st === 'failed') {
      finishFail(u.error || 'Update failed.');
    }
  }

  function onHealth(data) {
    var st = (data && data.update && data.update.state) || 'idle';
    if (!offlineSince) return;
    if (st === 'failed') {
      finishFail('Update failed during restart.');
      return;
    }
    if (st === 'done' || st === 'idle') {
      finishOk(data && data.version);
    }
  }

  function onOffline() {
    if (!offlineSince) offlineSince = Date.now();
    setPhase('offline');
    if (title) title.textContent = 'Console is offline';
    if (sub) {
      sub.textContent = 'The RadioTAK service is restarting. This page will keep waiting and return automatically.';
    }
    if (hint) hint.textContent = 'Leave this tab open. Refreshing may show this same waiting screen.';
    if (lastLog.indexOf('Console is unreachable') === -1) {
      setLog((lastLog ? lastLog.replace(/\s+$/, '') + '\n' : '') + 'Console is unreachable — waiting for RadioTAK to come back…');
    }
  }

  function finishOk(version) {
    if (finishing) return;
    finishing = true;
    stopPoll();
    setPhase('done');
    if (title) title.textContent = 'Update complete';
    if (sub) {
      sub.textContent = version
        ? ('Now running ' + version + '. Reloading the console…')
        : 'Reloading the console…';
    }
    if (hint) hint.textContent = '';
    pingSw('radiotak-updated');
    clearStore();
    var msg = 'Update complete' + (version ? ': ' + version : '');
    setTimeout(function () {
      window.location = '/system?msg=' + encodeURIComponent(msg);
    }, 1200);
  }

  function finishFail(err) {
    if (finishing) return;
    finishing = true;
    stopPoll();
    setPhase('failed');
    if (title) title.textContent = 'Update failed';
    if (sub) sub.textContent = err || 'See the log below.';
    if (hint) {
      hint.textContent = 'You can close this panel and try again, or SSH in and run: sudo radiotak update';
    }
    pingSw('radiotak-updated');
    clearStore();
    if (hint && !document.getElementById('update-close-btn')) {
      var closer = document.createElement('button');
      closer.type = 'button';
      closer.id = 'update-close-btn';
      closer.className = 'btn btn-primary';
      closer.style.marginTop = '12px';
      closer.textContent = 'Close';
      closer.addEventListener('click', function () {
        overlay.hidden = true;
        finishing = false;
      });
      hint.parentNode.appendChild(closer);
    }
  }

  function startJob(token) {
    finishing = false;
    lastLog = 'Starting update…\n';
    setLog(lastLog);
    begin();
    fetch('/api/v1/system/update', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': token,
      },
      body: JSON.stringify({ csrf_token: token }),
    }).then(function (r) {
      if (!r.ok) throw new Error('Could not start update (' + r.status + ')');
      return r.json();
    }).then(function (data) {
      if (data && data.update && data.update.log) setLog(data.update.log);
    }).catch(function (err) {
      finishFail(String(err.message || err));
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    overlay = $('update-overlay');
    term = $('update-term');
    title = $('update-overlay-title');
    sub = $('update-overlay-sub');
    hint = $('update-overlay-hint');
    var form = $('update-form');
    var csrfInput = form && form.querySelector('input[name="csrf_token"]');
    var csrf = csrfInput ? csrfInput.value : '';

    if (form) {
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        if (!csrf) return;
        startJob(csrf);
      });
    }

    var stored = loadStore();
    var params = new URLSearchParams(window.location.search);
    if ((stored && stored.active) || params.get('updating')) {
      if (stored && stored.log) setLog(stored.log);
      begin();
      return;
    }

    fetch('/api/v1/system/update', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        var st = data && data.update && data.update.state;
        if (st === 'running' || st === 'restarting') {
          if (data.update.log) setLog(data.update.log);
          begin();
        }
      })
      .catch(function () { /* ignore */ });
  });
})();
