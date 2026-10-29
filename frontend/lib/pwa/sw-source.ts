/**
 * Source du service worker (prompt 29, P2, ADR 0102), écrit à la main, sans bibliothèque.
 *
 * Il ne garde QUE des fichiers statiques versionnés (`/_next/static`, polices, icônes, le
 * manifeste) et la page `/hors-ligne`. Il ne garde JAMAIS : l'API, une page HTML, une réponse
 * qui pose ou lit un cookie, un export, un reçu. Aucune donnée de la boutique ne touche le
 * Cache Storage.
 *
 * Il ne s'active pas seul (`skipWaiting` seulement sur demande) : la page choisit un moment
 * sûr (`lib/pwa/update.ts`). Les caches d'un autre build sont supprimés à l'activation ; tout
 * est vidé sur le message `LOGOUT`, puis la pré-mise en cache (page hors ligne, ses styles et
 * ses polices, icônes, manifeste : aucune donnée) est remise — sans quoi une navigation sans
 * réseau après une déconnexion montrerait l'erreur du navigateur (prompt 32, P2).
 */
export function serviceWorkerSource(build: string): string {
  const cache = `coges-static-${build.replace(/[^A-Za-z0-9._-]/g, "-")}`;
  // Le commentaire ne porte que le nom de cache nettoyé : un `*/` dans l'étiquette le fermerait.
  return `/* CoGes — service worker, cache ${cache} (ADR 0102). */
"use strict";
const BUILD = ${JSON.stringify(build)};
const CACHE = ${JSON.stringify(cache)};
const OFFLINE = "/hors-ligne";
const PRECACHE = [OFFLINE, "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png"];

function isStatic(url) {
  return (
    url.origin === self.location.origin &&
    (url.pathname.startsWith("/_next/static/") ||
      url.pathname.startsWith("/icons/") ||
      url.pathname.startsWith("/brand/") ||
      url.pathname === "/manifest.webmanifest")
  );
}

// Un en-tête de cookie n'est jamais lisible depuis Fetch : ce qui garde les données hors du
// cache, c'est le chemin (\`isStatic\`, la page hors ligne), et \`no-store\` / \`private\` en plus.
function cacheable(response) {
  return (
    response &&
    response.ok &&
    response.type === "basic" &&
    !/no-store|private/.test(response.headers.get("cache-control") || "")
  );
}

// Fichiers statiques nommés par la page hors ligne (styles, polices) et par ses styles (polices).
function assetsOf(text, base) {
  const found = new Set();
  const pattern = /(?:href=["']|url\\(["']?)([^"')\\s]+\\.(?:css|woff2)(?:\\?[^"')\\s]*)?)/g;
  for (const match of text.matchAll(pattern)) {
    const url = new URL(match[1], base);
    if (url.origin === self.location.origin && url.pathname.startsWith("/_next/static/")) {
      found.add(url.pathname + url.search);
    }
  }
  return [...found];
}

function precache() {
  return caches.open(CACHE).then((cache) => {
    const keep = (path) =>
      fetch(path, { credentials: "omit", cache: "no-cache" }).then((response) => {
        if (!cacheable(response)) return "";
        const copy = response.clone();
        return cache.put(path, response).then(() =>
          /\\.css(\\?|$)|^\\/hors-ligne$/.test(path) ? copy.text() : "",
        );
      });
    const nested = (path) =>
      keep(path).then((text) =>
        Promise.all(
          assetsOf(text, new URL(path, self.location.origin)).map((asset) => nested(asset)),
        ),
      );
    return Promise.all(PRECACHE.map((path) => (path === OFFLINE ? nested(path) : keep(path))));
  });
}

self.addEventListener("install", (event) => {
  event.waitUntil(precache());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          names
            .filter((name) => name.startsWith("coges-") && name !== CACHE)
            .map((name) => caches.delete(name)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  const type = event.data && event.data.type;
  if (type === "SKIP_WAITING") self.skipWaiting();
  if (type === "LOGOUT") {
    event.waitUntil(
      caches
        .keys()
        .then((names) => Promise.all(names.map((name) => caches.delete(name))))
        .then(precache),
    );
  }
  if (type === "VERSION" && event.ports && event.ports[0]) event.ports[0].postMessage(BUILD);
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Navigation : toujours le réseau ; sans réseau, la page hors ligne.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() =>
        caches.match(OFFLINE).then((cached) => cached || Response.error()),
      ),
    );
    return;
  }

  // Fichiers versionnés : le cache d'abord, puis le réseau, gardé s'il le mérite.
  if (isStatic(url) && !request.headers.has("authorization")) {
    event.respondWith(
      caches.open(CACHE).then((cache) =>
        cache.match(request, { ignoreSearch: true }).then(
          (cached) =>
            cached ||
            fetch(request).then((response) => {
              if (cacheable(response)) cache.put(request, response.clone());
              return response;
            }),
        ),
      ),
    );
  }
  // Tout le reste (API, exports, reçus, données) : le réseau, sans rien garder.
});
`;
}
