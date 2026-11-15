/* ==========================================================================
   CrâniScan — Service Worker (PWA)
   Rôle : rendre l'app INSTALLABLE et résister aux coupures réseau.
   Stratégie :
     - « shell » (index, css, js, icône) : cache d'abord (l'interface s'ouvre
       toujours instantanément, même sans internet) ;
     - /api/* : réseau d'abord (les données médicales doivent être fraîches ;
       en cas d'échec → l'app affiche « hors ligne »).
   En production on ajouterait la synchronisation différée (la réponse au
   re-contrôle se met en file et part au retour du réseau).
   ========================================================================== */

const CACHE = "craniscan-v1";
const SHELL = [
  "/", "/index.html", "/css/app.css", "/js/api.js", "/js/app.js",
  "/js/exam.js", "/js/chat.js", "/js/followup.js", "/js/ble.js",
  "/manifest.json", "/icons/icon.svg",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
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
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws")) {
    e.respondWith(fetch(e.request)); // réseau d'abord pour les données médicales
    return;
  }
  e.respondWith(
    caches.match(e.request).then(
      (hit) => hit || fetch(e.request).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      })
    )
  );
});
