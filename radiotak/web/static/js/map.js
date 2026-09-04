/* TAK Portal–style basemap catalog on Leaflet + CoT markers */
(function (global) {
  'use strict';

  var LS_BASEMAP = 'radiotak-map-basemap';
  var DEFAULT_BASEMAP_ID = 'google-maps';

  var BASEMAPS = {
    'dark-matter': {
      label: 'CARTO Dark Matter',
      url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
      attr: '&copy; OpenStreetMap &copy; CARTO',
      subdomains: 'abcd',
      maxZoom: 20
    },
    positron: {
      label: 'CARTO Positron',
      url: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
      attr: '&copy; OpenStreetMap &copy; CARTO',
      subdomains: 'abcd',
      maxZoom: 20
    },
    voyager: {
      label: 'CARTO Voyager',
      url: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
      attr: '&copy; OpenStreetMap &copy; CARTO',
      subdomains: 'abcd',
      maxZoom: 20
    },
    satellite: {
      label: 'Esri Satellite',
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      attr: 'Esri, Maxar, Earthstar Geographics',
      maxZoom: 19
    },
    topo: {
      label: 'OpenTopoMap Topographic',
      url: 'https://tile.opentopomap.org/{z}/{x}/{y}.png',
      attr: '&copy; OpenTopoMap, OSM',
      maxZoom: 17
    },
    'google-maps': {
      label: 'Google Maps',
      url: 'https://mts1.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}&s=Gal&apistyle=s.t:2|s.e:l|p.v:off',
      attr: 'Google',
      maxZoom: 20
    },
    'google-satellite': {
      label: 'Google Satellite',
      url: 'https://mt1.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}',
      attr: 'Google',
      maxZoom: 22
    },
    'google-hybrid': {
      label: 'Google Hybrid',
      url: 'https://mt1.google.com/vt/lyrs=y&hl=en&x={x}&y={y}&z={z}',
      attr: 'Google',
      maxZoom: 22
    },
    'google-terrain': {
      label: 'Google Terrain',
      url: 'https://mts1.google.com/vt/lyrs=p&hl=en&x={x}&y={y}&z={z}',
      attr: 'Google',
      maxZoom: 18
    },
    'google-traffic': {
      label: 'Google Traffic',
      url: 'https://mt0.google.com/vt/lyrs=m,parking,traffic&hl=en&x={x}&y={y}&z={z}&apistyle=s.t:2|s.e:l|p.v:off',
      attr: 'Google',
      maxZoom: 18
    }
  };

  function normalizeBasemapId(id) {
    var saved = String(id || '').trim() || DEFAULT_BASEMAP_ID;
    if (saved === 'dark' || saved === 'light') {
      saved = saved === 'light' ? 'voyager' : 'dark-matter';
    } else if (/-nolabels$/.test(saved)) {
      saved = saved.replace(/-nolabels$/, '');
    }
    if (!BASEMAPS[saved]) saved = DEFAULT_BASEMAP_ID;
    return saved;
  }

  function savedBasemapId() {
    try {
      return normalizeBasemapId(localStorage.getItem(LS_BASEMAP));
    } catch (e) {
      return DEFAULT_BASEMAP_ID;
    }
  }

  function persistBasemapId(id) {
    try {
      localStorage.setItem(LS_BASEMAP, normalizeBasemapId(id));
    } catch (e) { /* ignore */ }
  }

  function makeTileLayer(id) {
    var entry = BASEMAPS[normalizeBasemapId(id)];
    var opts = {
      maxZoom: entry.maxZoom || 18,
      attribution: entry.attr
    };
    if (entry.subdomains) opts.subdomains = entry.subdomains;
    return L.tileLayer(entry.url, opts);
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
    var basemapId = normalizeBasemapId(opts.basemap || savedBasemapId());
    var layer = makeTileLayer(basemapId).addTo(map);
    map._rtTileLayer = layer;
    map._rtBasemapId = basemapId;

    var baseLayers = {};
    Object.keys(BASEMAPS).forEach(function (id) {
      baseLayers[BASEMAPS[id].label] = (id === basemapId) ? layer : makeTileLayer(id);
    });

    var control = L.control.layers(baseLayers, null, {
      position: opts.layersPosition || 'topright',
      collapsed: opts.layersCollapsed !== false
    }).addTo(map);

    map.on('baselayerchange', function (e) {
      var nextId = DEFAULT_BASEMAP_ID;
      Object.keys(BASEMAPS).forEach(function (id) {
        if (BASEMAPS[id].label === e.name) nextId = id;
      });
      map._rtBasemapId = nextId;
      map._rtTileLayer = e.layer;
      persistBasemapId(nextId);
    });

    map.setBasemap = function (id) {
      id = normalizeBasemapId(id);
      if (map._rtBasemapId === id) return;
      var next = makeTileLayer(id);
      map.removeLayer(map._rtTileLayer);
      next.addTo(map);
      map._rtTileLayer = next;
      map._rtBasemapId = id;
      persistBasemapId(id);
    };

    // Theme no longer forces dark OSM — keep chosen TAK Portal basemap.
    map.watchTheme = function () { /* no-op for compatibility */ };

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

    map._rtLayersControl = control;
    return map;
  }

  global.RadioTakMap = {
    create: createMap,
    cotIcon: cotIcon,
    BASEMAPS: BASEMAPS,
    DEFAULT_BASEMAP_ID: DEFAULT_BASEMAP_ID,
    normalizeBasemapId: normalizeBasemapId,
    savedBasemapId: savedBasemapId
  };
})(window);
