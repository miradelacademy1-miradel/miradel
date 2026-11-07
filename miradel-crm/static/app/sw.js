// Ilova qobigʻini (HTML/CSS/JS) oflayn ochish uchun. API soʻrovlariga tegmaydi.
var C = "miradel-shell-v6";
self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(C).then(function (c) { return c.addAll(["./", "./index.html", "./teacher.html", "./manager.html", "./chat.js", "./config.js", "./update.js", "./manifest.json", "./icons/icon-192.png"]); }));
  self.skipWaiting();
});
self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (ks) { return Promise.all(ks.filter(function (k) { return k !== C; }).map(function (k) { return caches.delete(k); })); }));
  self.clients.claim();
});
self.addEventListener("fetch", function (e) {
  var u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.indexOf("/api/") === 0) return;
  e.respondWith(fetch(e.request).then(function (r) {
    var cp = r.clone(); caches.open(C).then(function (c) { c.put(e.request, cp); }); return r;
  }).catch(function () { return caches.match(e.request).then(function (m) { return m || caches.match("./index.html"); }); }));
});
