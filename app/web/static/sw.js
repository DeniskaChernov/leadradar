/* Lead Radar PWA offline shell — cache version must match UI ?v= in templates. */
const CACHE_VERSION = "13.54.0-f5-hot-ops";
const CACHE_NAME = "leadradar-shell-13.54.0-f5-hot-ops";
const OFFLINE_URL = "/static/offline.html";
const PRECACHE_URLS = [
  OFFLINE_URL,
  "/static/manifest.webmanifest",
  `/static/app.css?v=${CACHE_VERSION}`,
  `/static/app.js?v=${CACHE_VERSION}`,
  "/static/icons/icon.svg",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key.startsWith("leadradar-shell-") && key !== CACHE_NAME).map((key) => caches.delete(key)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") {
    return;
  }
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return;
  }
  // API и live-данные никогда не кэшируем.
  if (url.pathname.startsWith("/api/") || url.pathname === "/health" || url.pathname === "/ready") {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => response)
        .catch(async () => {
          const cached = await caches.match(OFFLINE_URL);
          return cached || Response.error();
        })
    );
    return;
  }

  if (!url.pathname.startsWith("/static/")) {
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) {
        return cached;
      }
      return fetch(request).then((response) => {
        if (!response.ok) {
          return response;
        }
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
        return response;
      });
    })
  );
});
