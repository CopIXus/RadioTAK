/* Serve a waiting page when the console is down during an update. */
var CACHE = 'radiotak-update-v1';
var OFFLINE_URL = '/static/update-offline.html';

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      return cache.addAll([OFFLINE_URL]);
    }).then(function () {
      return self.skipWaiting();
    })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', function (event) {
  if (event.request.mode !== 'navigate') return;
  event.respondWith(
    fetch(event.request).catch(function () {
      return caches.match(OFFLINE_URL).then(function (cached) {
        return cached || Response.error();
      });
    })
  );
});
