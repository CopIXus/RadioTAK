/* RadioTAK shared UI helpers — toast, confirm modal, help popovers, busy buttons */
(function () {
  'use strict';

  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  function ensureToastWrap() {
    var el = qs('#toast-wrap');
    if (!el) {
      el = document.createElement('div');
      el.id = 'toast-wrap';
      el.className = 'toast-wrap';
      el.setAttribute('aria-live', 'polite');
      document.body.appendChild(el);
    }
    return el;
  }

  window.toast = function (msg, kind) {
    if (!msg) return;
    var wrap = ensureToastWrap();
    var t = document.createElement('div');
    t.className = 'toast ' + (kind || 'info');
    t.textContent = msg;
    wrap.appendChild(t);
    setTimeout(function () {
      t.style.opacity = '0';
      setTimeout(function () { t.remove(); }, 200);
    }, 3500);
  };

  function flashFromQuery() {
    var params = new URLSearchParams(window.location.search);
    var msg = params.get('msg');
    var err = params.get('err');
    if (err) toast(err, 'error');
    else if (msg) toast(msg, 'success');
  }

  function ensureModal() {
    var overlay = qs('#confirm-modal');
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.id = 'confirm-modal';
    overlay.className = 'modal-overlay';
    overlay.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title">' +
      '<h3 id="confirm-title">Confirm</h3>' +
      '<p id="confirm-body"></p>' +
      '<div class="modal-actions">' +
      '<button type="button" class="btn" id="confirm-cancel">Cancel</button>' +
      '<button type="button" class="btn btn-danger" id="confirm-ok">Confirm</button>' +
      '</div></div>';
    document.body.appendChild(overlay);
    return overlay;
  }

  window.confirmModal = function (message, opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      var overlay = ensureModal();
      qs('#confirm-title', overlay).textContent = opts.title || 'Confirm';
      qs('#confirm-body', overlay).textContent = message || 'Are you sure?';
      var ok = qs('#confirm-ok', overlay);
      ok.textContent = opts.okLabel || 'Confirm';
      ok.className = 'btn ' + (opts.danger === false ? 'btn-primary' : 'btn-danger');
      overlay.classList.add('open');
      function done(val) {
        overlay.classList.remove('open');
        ok.onclick = null;
        qs('#confirm-cancel', overlay).onclick = null;
        resolve(val);
      }
      ok.onclick = function () { done(true); };
      qs('#confirm-cancel', overlay).onclick = function () { done(false); };
      overlay.onclick = function (e) { if (e.target === overlay) done(false); };
    });
  };

  function wireConfirms() {
    qsa('[data-confirm]').forEach(function (el) {
      if (el.dataset.confirmBound) return;
      el.dataset.confirmBound = '1';
      el.addEventListener('click', function (e) {
        var msg = el.getAttribute('data-confirm');
        if (!msg) return;
        e.preventDefault();
        confirmModal(msg, {
          title: el.getAttribute('data-confirm-title') || 'Confirm',
          okLabel: el.getAttribute('data-confirm-ok') || 'Confirm',
          danger: el.getAttribute('data-confirm-danger') !== 'false',
        }).then(function (ok) {
          if (!ok) return;
          if (el.tagName === 'A' && el.href) {
            window.location = el.href;
            return;
          }
          var form = el.closest('form');
          if (form) {
            if (typeof form.requestSubmit === 'function') form.requestSubmit(el);
            else form.submit();
          }
        });
      });
    });
  }

  function closeAllPopovers(except) {
    qsa('.help-popover.open').forEach(function (p) {
      if (p === except) return;
      p.classList.remove('open');
      var btn = p._btn;
      if (btn) btn.setAttribute('aria-expanded', 'false');
    });
  }

  function wireHelp() {
    qsa('[data-help]').forEach(function (btn) {
      if (btn.dataset.helpBound) return;
      btn.dataset.helpBound = '1';
      var pop = btn.nextElementSibling;
      if (!pop || !pop.classList.contains('help-popover')) {
        var key = btn.getAttribute('data-help');
        var data = (window.RADIOTAK_HELP || {})[key];
        if (!data) return;
        pop = document.createElement('div');
        pop.className = 'help-popover';
        pop.setAttribute('role', 'tooltip');
        var html = '<strong>' + (data.label || key) + '</strong>';
        if (data.what) html += '<div>' + data.what + '</div>';
        if (data.where) html += '<div class="hp-where">' + data.where + '</div>';
        if (data.example) html += '<div class="hp-example">' + data.example + '</div>';
        pop.innerHTML = html;
        btn.parentNode.appendChild(pop);
      }
      pop._btn = btn;
      btn.setAttribute('aria-expanded', 'false');
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var open = pop.classList.contains('open');
        closeAllPopovers();
        if (!open) {
          pop.classList.add('open');
          btn.setAttribute('aria-expanded', 'true');
        }
      });
    });
    document.addEventListener('click', function () { closeAllPopovers(); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeAllPopovers();
    });
  }

  function wirePasswordReveal() {
    qsa('[data-password-toggle]').forEach(function (btn) {
      if (btn.dataset.toggleBound) return;
      btn.dataset.toggleBound = '1';
      btn.addEventListener('click', function () {
        var wrap = btn.closest('.password-wrap');
        var input = wrap && wrap.querySelector('input');
        if (!input) return;
        var show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        btn.classList.toggle('is-revealed', show);
        btn.setAttribute('aria-pressed', show ? 'true' : 'false');
        btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
        btn.setAttribute('title', show ? 'Hide password' : 'Show password');
      });
    });
  }

  function wireBusy() {
    qsa('form[data-busy]').forEach(function (form) {
      form.addEventListener('submit', function () {
        qsa('button[type=submit]', form).forEach(function (btn) {
          btn.classList.add('is-busy');
          btn.disabled = true;
          if (!btn.dataset.origLabel) btn.dataset.origLabel = btn.textContent;
          btn.textContent = form.getAttribute('data-busy') || 'Working…';
        });
      });
    });
  }

  function wireSidebar() {
    var toggle = qs('#sidebar-toggle');
    var backdrop = qs('#sidebar-backdrop');
    function open() { document.body.classList.add('sidebar-open'); }
    function close() { document.body.classList.remove('sidebar-open'); }
    if (toggle) toggle.addEventListener('click', function () {
      document.body.classList.toggle('sidebar-open');
    });
    if (backdrop) backdrop.addEventListener('click', close);
  }

  function wireTabs() {
    qsa('[data-tabs]').forEach(function (root) {
      var btns = qsa('.tab-btn', root);
      var panels = qsa('.tab-panel', root);
      btns.forEach(function (btn) {
        btn.addEventListener('click', function () {
          var id = btn.getAttribute('data-tab');
          btns.forEach(function (b) { b.classList.toggle('active', b === btn); });
          panels.forEach(function (p) {
            p.classList.toggle('active', p.id === id || p.getAttribute('data-panel') === id);
          });
        });
      });
    });
  }

  window.setWsBadge = function (el, state) {
    if (!el) return;
    el.classList.remove('live', 'dead');
    if (state === 'live') el.classList.add('live');
    else if (state === 'dead') el.classList.add('dead');
  };

  function applyVersionStatus(data) {
    var meta = qs('#version-meta');
    var label = qs('#version-label');
    var pill = qs('#update-pill');
    if (!meta || !label) return;
    if (data && data.installed) label.textContent = data.installed;
    var outdated = !!(data && data.update_available);
    meta.classList.toggle('version-outdated', outdated);
    if (pill) {
      if (outdated) {
        pill.hidden = false;
        if (data.latest) pill.title = 'Update available: ' + data.latest;
      } else {
        pill.hidden = true;
      }
    }
  }

  function pollVersion() {
    var meta = qs('#version-meta');
    if (!meta) return;
    fetch('/api/v1/version', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { if (data) applyVersionStatus(data); })
      .catch(function () { /* offline / unauthenticated */ });
  }

  document.addEventListener('DOMContentLoaded', function () {
    flashFromQuery();
    wireConfirms();
    wireHelp();
    wirePasswordReveal();
    wireBusy();
    wireSidebar();
    wireTabs();
    pollVersion();
    setInterval(pollVersion, 120000);
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/update-sw.js', { scope: '/' }).catch(function () { /* private mode / http */ });
    }
  });
})();
