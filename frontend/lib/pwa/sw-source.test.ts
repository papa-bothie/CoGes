import { describe, expect, it } from "vitest";

import { serviceWorkerSource } from "./sw-source";

/**
 * Le worker écrit à la main (ADR 0102), exécuté dans un faux environnement : Cache Storage en
 * mémoire, réseau simulé, événements `install` et `message`.
 */
const OFFLINE_HTML = `<!doctype html><html><head>
<link rel="stylesheet" href="/_next/static/chunks/app-1a2b.css?dpl=v1" data-precedence="next"/>
<link rel="preload" href="/_next/static/media/figtree-3c4d.woff2" as="font" type="font/woff2"/>
</head><body><main><h1>Pas de connexion</h1></main></body></html>`;
const CSS = `body{font-family:Figtree}@font-face{src:url(../media/figtree-3c4d.woff2) format("woff2")}`;

function environment(build = "v1") {
  const stores = new Map<string, Map<string, Response>>();
  const listeners = new Map<string, (event: unknown) => void>();
  const network: Record<string, () => Response> = {
    "/hors-ligne": () => new Response(OFFLINE_HTML, { headers: { "content-type": "text/html" } }),
    "/manifest.webmanifest": () => new Response("{}"),
    "/icons/icon-192.png": () => new Response("png"),
    "/icons/icon-512.png": () => new Response("png"),
    "/_next/static/chunks/app-1a2b.css": () => new Response(CSS),
    "/_next/static/media/figtree-3c4d.woff2": () => new Response("font"),
  };
  const path = (input: string) => new URL(input, "https://coges.test").pathname;
  const caches = {
    open: async (name: string) => {
      if (!stores.has(name)) stores.set(name, new Map());
      const store = stores.get(name)!;
      return {
        put: async (request: string, response: Response) => void store.set(path(request), response),
        match: async (request: string) => store.get(path(request)),
        keys: async () => [...store.keys()],
      };
    },
    keys: async () => [...stores.keys()],
    delete: async (name: string) => stores.delete(name),
    match: async (request: string) => {
      for (const store of stores.values())
        if (store.has(path(request))) return store.get(path(request));
      return undefined;
    },
  };
  const fetch = async (input: string) => {
    const answer = network[path(input)];
    const response = answer ? answer() : new Response("", { status: 404 });
    // Une réponse de même origine est « basic » dans un vrai navigateur.
    return Object.defineProperty(response, "type", { value: "basic" });
  };
  const self = {
    location: new URL("https://coges.test/sw.js"),
    addEventListener: (type: string, listener: (event: unknown) => void) =>
      listeners.set(type, listener),
    skipWaiting: () => undefined,
    clients: { claim: async () => undefined },
  };
  new Function("self", "caches", "fetch", serviceWorkerSource(build))(self, caches, fetch);

  const dispatch = async (type: string, data?: unknown) => {
    const pending: Promise<unknown>[] = [];
    listeners.get(type)?.({
      data,
      waitUntil: (promise: Promise<unknown>) => pending.push(promise),
    });
    await Promise.all(pending);
  };
  const cached = async () => {
    const all: string[] = [];
    for (const store of stores.values()) all.push(...store.keys());
    return all.sort();
  };
  return { dispatch, cached, stores };
}

const PRECACHED = [
  "/_next/static/chunks/app-1a2b.css",
  "/_next/static/media/figtree-3c4d.woff2",
  "/hors-ligne",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/manifest.webmanifest",
];

describe("service worker (ADR 0102)", () => {
  it("garde la page hors ligne avec ses styles et ses polices", async () => {
    const sw = environment();
    await sw.dispatch("install");
    expect(await sw.cached()).toEqual(PRECACHED);
  });

  it("la déconnexion vide tout, puis remet la page hors ligne (P2, prompt 32)", async () => {
    const sw = environment();
    await sw.dispatch("install");
    (await (sw.stores.get([...sw.stores.keys()][0]!) ?? new Map())).set(
      "/_next/static/chunks/page-9z.js",
      new Response("js"),
    );
    await sw.dispatch("message", { type: "LOGOUT" });
    expect(await sw.cached()).toEqual(PRECACHED);
  });

  it("un identifiant de build ne casse jamais la source du worker", () => {
    expect(() => environment("v1*/ throw 1; /*")).not.toThrow();
    expect(serviceWorkerSource("v1*/x")).not.toContain("v1*/x */");
  });

  it("aucune règle qui ne peut rien voir : `set-cookie` n'est jamais lisible côté Fetch", () => {
    expect(serviceWorkerSource("v1")).not.toContain("set-cookie");
  });
});
