/**
 * JewelDesk Service Worker
 * Production-ready Progressive Web App worker for jewellery retail management.
 */

const CACHE_VERSION = 'jeweldesk-v1.1.0';
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const RUNTIME_CACHE = `${CACHE_VERSION}-runtime`;

// Shell assets to precache on install
const PRECACHE_ASSETS = [
  '/offline/',
  '/manifest.json',
  '/accounts/login/',
  '/static/css/style.css',
  '/static/css/login.css',
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png',
  '/static/icons/favicon-32x32.png',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js'
];

// Install: precache critical assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then(async (cache) => {
      // Use individual puts with error handling to avoid 1 failed request breaking entire install
      for (const asset of PRECACHE_ASSETS) {
        try {
          const req = new Request(asset, { mode: 'cors' });
          const res = await fetch(req);
          if (res.ok) {
            await cache.put(req, res);
          }
        } catch (err) {
          // If a CDN or individual resource fails, proceed with remaining assets
          console.warn('[SW] Precache skipped for:', asset, err);
        }
      }
    }).then(() => self.skipWaiting())
  );
});

// Activate: clean up older cache versions
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== STATIC_CACHE && key !== RUNTIME_CACHE) {
            console.log('[SW] Removing old cache:', key);
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch: intelligent caching strategies
self.addEventListener('fetch', (event) => {
  const { request } = event;

  // Only intercept GET requests
  if (request.method !== 'GET') {
    return;
  }

  const url = new URL(request.url);

  // Skip chrome-extension and non-http schemes
  if (!url.protocol.startsWith('http')) {
    return;
  }

  // 1. Navigation (HTML Pages): Network-first with offline fallback
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.ok) {
            const responseClone = networkResponse.clone();
            caches.open(RUNTIME_CACHE).then((cache) => {
              cache.put(request, responseClone);
            });
          }
          return networkResponse;
        })
        .catch(async () => {
          // Try to return previously cached page first
          const cachedPage = await caches.match(request);
          if (cachedPage) {
            return cachedPage;
          }
          // Otherwise return the dedicated offline page
          const offlineFallback = await caches.match('/offline/');
          if (offlineFallback) {
            return offlineFallback;
          }
          return new Response(
            '<html><head><title>JewelDesk Offline</title></head><body style="font-family:sans-serif;text-align:center;padding:50px;"><h2>JewelDesk is Offline</h2><p>Please check your connection and retry.</p></body></html>',
            { headers: { 'Content-Type': 'text/html' } }
          );
        })
    );
    return;
  }

  // 2. Static Assets (CSS, JS, Fonts, Images): Stale-While-Revalidate
  const isStaticAsset =
    request.destination === 'style' ||
    request.destination === 'script' ||
    request.destination === 'font' ||
    request.destination === 'image' ||
    url.pathname.startsWith('/static/');

  if (isStaticAsset) {
    event.respondWith(
      caches.match(request).then((cachedResponse) => {
        const fetchPromise = fetch(request)
          .then((networkResponse) => {
            if (networkResponse && networkResponse.ok) {
              const responseClone = networkResponse.clone();
              caches.open(RUNTIME_CACHE).then((cache) => {
                cache.put(request, responseClone);
              });
            }
            return networkResponse;
          })
          .catch(() => cachedResponse);

        return cachedResponse || fetchPromise;
      })
    );
    return;
  }

  // 3. Default: Network with Cache Fallback
  event.respondWith(
    fetch(request).catch(() => caches.match(request))
  );
});

// Client communication: allow manual skipWaiting triggers
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
