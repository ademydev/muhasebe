const CACHE = 'hesap-v4';
const BASE = new URL('./', self.registration.scope);
const FILES = ['./', './style.css', './app.js', './browser-store.js', './manifest.webmanifest'];
self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(FILES.map(file => new URL(file, BASE))))));
self.addEventListener('activate', event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))));
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith('/api/')) return;
  event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request).then(response => {
    const copy = response.clone(); caches.open(CACHE).then(cache => cache.put(event.request, copy)); return response;
  })));
});
