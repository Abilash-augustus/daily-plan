// Today's Plan — service worker
// Caches static assets (icons, manifest) cache-first for offline support.
// Serves index.html network-first so deployed bug fixes show up on next reload
// instead of being trapped behind a stale cached HTML.
// Plan data is fetched live from GitHub Gist on every load (no caching).

const CACHE = 'adhd-pwa-shell-v6'; // bump on every deploy that changes shell behavior
const SHELL = [
  './manifest.webmanifest',
  './icon-192.png',
  './icon-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

function isHtmlRequest(request) {
  if (request.mode === 'navigate') return true;
  const url = new URL(request.url);
  return url.pathname === '/' || url.pathname.endsWith('/') || url.pathname.endsWith('.html');
}

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  // Always fetch plan data fresh (don't cache GitHub API responses)
  if (url.hostname === 'api.github.com' || url.hostname === 'gist.githubusercontent.com') {
    return; // let it pass through to the network without SW involvement
  }

  // Network-first for the HTML shell — picks up new deploys on next reload.
  if (isHtmlRequest(event.request)) {
    event.respondWith(
      fetch(event.request)
        .then((res) => {
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((cache) => cache.put(event.request, copy)).catch(() => {});
          }
          return res;
        })
        .catch(() => caches.match(event.request).then((cached) => cached || caches.match('./index.html')))
    );
    return;
  }

  // Cache-first for everything else (icons, manifest, etc.)
  event.respondWith(
    caches.match(event.request).then((cached) => {
      return cached || fetch(event.request).then((res) => {
        if (res.ok && event.request.method === 'GET') {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, copy)).catch(() => {});
        }
        return res;
      }).catch(() => cached);
    })
  );
});

// Push notifications (wired up later — placeholder)
self.addEventListener('push', (event) => {
  let data = { title: 'Brain check', body: 'something\'s waiting in the plan' };
  try {
    if (event.data) data = event.data.json();
  } catch (e) {}
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: './icon-192.png',
      badge: './icon-192.png',
      tag: 'plan-nudge',
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(self.clients.openWindow('./'));
});
