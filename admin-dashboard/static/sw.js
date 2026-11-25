/**
 * Homelab OS (HL-OS) — Ultra-Lightweight Preact PWA Service Worker
 * Network-first for HTML & APIs (instant updates!), cache-first for immutable hashed /assets/
 */

const CACHE_NAME = 'homelab-pwa-v4';
const APP_SHELL = [
  '/dashboard',
  '/login',
  '/static/manifest.json'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      cache.addAll(APP_SHELL).catch((err) => {
        console.warn('Shell cache partial:', err);
      })
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.map((key) => (key !== CACHE_NAME ? caches.delete(key) : null)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET') return;

  // API endpoints: Network-first with cache fallback when offline
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response.status === 200) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
          }
          return response;
        })
        .catch(() =>
          caches.match(event.request).then(
            (cached) =>
              cached ||
              new Response(
                JSON.stringify({ error: 'offline', message: 'Network offline. Using local mode.' }),
                { headers: { 'Content-Type': 'application/json' }, status: 503 }
              )
          )
        )
    );
    return;
  }

  // Immutable content-hashed Vite assets: Cache-first
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached;
        return fetch(event.request).then((res) => {
          if (res && res.status === 200) {
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, res.clone()));
          }
          return res;
        });
      })
    );
    return;
  }

  // HTML shell & other routes: Network-first so new deployments always render immediately
  event.respondWith(
    fetch(event.request)
      .then((res) => {
        if (res && res.status === 200) {
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, res.clone()));
        }
        return res;
      })
      .catch(() => caches.match(event.request))
  );
});
