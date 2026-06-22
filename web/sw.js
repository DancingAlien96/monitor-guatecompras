// Service worker: hace la app instalable (cachea el "shell"), funciona offline
// para la interfaz, y en Android revisa concursos nuevos en segundo plano.
importScripts('vendor/fflate.js', 'core.js');

var CACHE = 'gc-v1';
var SHELL = ['./', 'index.html', 'core.js', 'vendor/fflate.js', 'manifest.json',
  'icon-192.png', 'icon-512.png', 'apple-touch-icon.png'];

self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(SHELL); })
    .then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (ks) {
    return Promise.all(ks.filter(function (k) { return k !== CACHE; })
      .map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

// Solo se cachea el shell (mismo origen). Las llamadas a la API pasan directo.
self.addEventListener('fetch', function (e) {
  var u = new URL(e.request.url);
  if (u.origin === self.location.origin) {
    e.respondWith(caches.match(e.request).then(function (r) { return r || fetch(e.request); }));
  }
});

// Revision periodica en segundo plano (Android/Chrome, mejor esfuerzo).
self.addEventListener('periodicsync', function (e) {
  if (e.tag === 'concursos') e.waitUntil(revisar());
});

async function revisar() {
  try {
    var lista = await obtenerConcursos();
    var vistos = await leerVistos();
    var nuevos = lista.filter(function (c) { return !vistos.has(c.ocid || c.nog); });
    if (vistos.size > 0 && nuevos.length) {
      await self.registration.showNotification('Nuevos concursos', {
        body: nuevos.length + ' concurso(s) nuevo(s) de compra directa que coinciden con tus filtros.',
        icon: 'icon-192.png', badge: 'icon-192.png', data: { url: './' },
      });
    }
    await marcarVistos(nuevos.map(function (c) { return c.ocid || c.nog; }));
  } catch (e) {}
}

self.addEventListener('notificationclick', function (e) {
  e.notification.close();
  var url = (e.notification.data && e.notification.data.url) || './';
  e.waitUntil(clients.matchAll({ type: 'window' }).then(function (cl) {
    for (var i = 0; i < cl.length; i++)
      if (cl[i].url.indexOf(self.location.origin) === 0 && 'focus' in cl[i]) return cl[i].focus();
    if (clients.openWindow) return clients.openWindow(url);
  }));
});
