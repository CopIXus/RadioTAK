/* Theme-aware Leaflet map + CoT-style markers */
(function (global) {
  'use strict';

  var TILES = {
    dark: {
      url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
      attr: '&copy; OpenStreetMap &copy; CARTO'
    },
    light: {
      url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      attr: '&copy; OpenStreetMap'
    }
  };

  function themeName() {
    return (document.documentElement.getAttribute('data-theme') || 'dark') === 'light' ? 'light' : 'dark';
  }

  function cotIcon(color) {
    var c = color || '#06b6d4';
    return L.divIcon({
      className: '',
      html: '<div class="cot-marker" style="background:' + c + '"></div>',
      iconSize: [18, 18],
      iconAnchor: [9, 9],
      popupAnchor: [0, -10]
    });
  }

  function createMap(elId, opts) {
    opts = opts || {};
    var el = document.getElementById(elId);
    if (!el || typeof L === 'undefined') return null;
    var map = L.map(elId).setView(opts.center || [39.5, -98.35], opts.zoom || 4);
    var theme = themeName();
    var layer = L.tileLayer(TILES[theme].url, {
      maxZoom: 18,
      attribution: TILES[theme].attr,
      subdomains: 'abcd'
    }).addTo(map);
    map._rtTileLayer = layer;
    map._rtTheme = theme;

    map.setTheme = function (name) {
      name = name === 'light' ? 'light' : 'dark';
      if (map._rtTheme === name) return;
      map.removeLayer(map._rtTileLayer);
      map._rtTileLayer = L.tileLayer(TILES[name].url, {
        maxZoom: 18,
        attribution: TILES[name].attr,
        subdomains: 'abcd'
      }).addTo(map);
      map._rtTheme = name;
    };

    map.watchTheme = function () {
      var obs = new MutationObserver(function () {
        map.setTheme(themeName());
      });
      obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    };

    map.plotPoints = function (points, group) {
      if (group) group.clearLayers();
      else group = L.layerGroup().addTo(map);
      var bounds = [];
      (points || []).forEach(function (p) {
        if (p.lat == null || p.lon == null) return;
        var color = p.marker_color || '#06b6d4';
        var m = L.marker([p.lat, p.lon], { icon: cotIcon(color) });
        var label = p.callsign || p.radio_id || 'Radio';
        m.bindTooltip(label, {
          permanent: true,
          direction: 'top',
          offset: [0, -12],
          className: 'cot-label'
        });
        var lines = [
          label,
          (p.lat.toFixed ? p.lat.toFixed(5) : p.lat) + ', ' + (p.lon.toFixed ? p.lon.toFixed(5) : p.lon)
        ];
        if (p.cot_type) lines.push('Type: ' + p.cot_type);
        if (p.icon) lines.push('Icon: ' + p.icon);
        if (p.observed_at) lines.push('Heard: ' + p.observed_at);
        m.bindPopup(lines.join('<br/>'));
        group.addLayer(m);
        bounds.push([p.lat, p.lon]);
      });
      if (bounds.length) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 14 });
      return group;
    };

    return map;
  }

  global.RadioTakMap = { create: createMap, cotIcon: cotIcon, themeName: themeName };
})(window);
