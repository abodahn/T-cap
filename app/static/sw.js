/* T-CAP service worker — enables installability + a light offline shell. */
const CACHE = "tcap-v1";
const SHELL = [
  "/static/css/tc-brand.css",
  "/static/css/app.css",
  "/static/img/logo-mark.png",
  "/static/img/logo-mark-white.png",
  "/static/img/logo-lockup-white.png",
  "/static/img/favicon-192.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // Static assets: cache-first. Everything else: network-first (fresh data).
  if (url.pathname.startsWith("/static/")) {
    e.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        return res;
      }).catch(() => hit))
    );
  } else {
    e.respondWith(fetch(req).catch(() => caches.match(req)));
  }
});
