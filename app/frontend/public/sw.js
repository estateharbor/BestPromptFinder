// Minimal service worker — enables "install as app" (PWA).
// Network-first passthrough so content is always fresh; a fetch handler is required
// for the browser's install criteria. No aggressive caching, so no stale API data.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
