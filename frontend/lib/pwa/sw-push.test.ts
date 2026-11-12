import { describe, expect, it, vi } from "vitest";

import { serviceWorkerSource } from "./sw-source";

/**
 * Notifications sur le téléphone (ADR 0120) : le worker affiche ce que le serveur a écrit,
 * ouvre l'écran nommé, et ne mène jamais hors de CoGes. Faux environnement : pas de navigateur.
 */
function environment(windows: { url: string }[] = []) {
  const listeners = new Map<string, (event: unknown) => void>();
  const shown: { title: string; options: Record<string, unknown> }[] = [];
  const navigated: string[] = [];
  const opened: string[] = [];
  const clients = windows.map((window) => ({
    url: window.url,
    focus: vi.fn(async function (this: unknown) {
      return this;
    }),
    navigate: vi.fn(async (url: string) => {
      navigated.push(url);
      return null;
    }),
  }));
  const self = {
    location: new URL("https://coges.test/sw.js"),
    addEventListener: (type: string, listener: (event: unknown) => void) =>
      listeners.set(type, listener),
    skipWaiting: () => undefined,
    registration: {
      showNotification: async (title: string, options: Record<string, unknown>) =>
        void shown.push({ title, options }),
    },
    clients: {
      claim: async () => undefined,
      matchAll: async () => clients,
      openWindow: async (url: string) => void opened.push(url),
    },
  };
  const caches = { open: vi.fn(), keys: vi.fn(async () => []), match: vi.fn() };
  const fetch = vi.fn();
  new Function("self", "caches", "fetch", serviceWorkerSource("v1"))(self, caches, fetch);

  const dispatch = async (type: string, event: Record<string, unknown>) => {
    const pending: Promise<unknown>[] = [];
    listeners.get(type)?.({
      ...event,
      waitUntil: (promise: Promise<unknown>) => pending.push(promise),
    });
    await Promise.all(pending);
  };
  const push = (payload: unknown) =>
    dispatch("push", {
      data:
        payload === undefined
          ? null
          : {
              json: () => {
                if (typeof payload === "string") return JSON.parse(payload);
                return payload;
              },
            },
    });
  const click = (url: unknown) =>
    dispatch("notificationclick", { notification: { data: { url }, close: vi.fn() } });
  return { shown, navigated, opened, push, click, caches, fetch };
}

describe("push", () => {
  it("affiche le titre et le texte du serveur, avec le chemin à ouvrir", async () => {
    const sw = environment();
    await sw.push({
      title: "Riz 25 kg est épuisé",
      body: "Vous ne pouvez plus en vendre.",
      url: "/inventory/receive?product=abc",
      tag: "coges-alertes",
    });
    expect(sw.shown).toHaveLength(1);
    expect(sw.shown[0]!.title).toBe("Riz 25 kg est épuisé");
    expect(sw.shown[0]!.options).toMatchObject({
      body: "Vous ne pouvez plus en vendre.",
      tag: "coges-alertes",
      data: { url: "/inventory/receive?product=abc" },
    });
  });

  it("ne garde rien en cache et n'appelle aucun réseau", async () => {
    const sw = environment();
    await sw.push({ title: "Vente n° 42 annulée par Awa", url: "/sales/1" });
    expect(sw.caches.open).not.toHaveBeenCalled();
    expect(sw.fetch).not.toHaveBeenCalled();
  });

  it.each(["//evil.example", "https://evil.example/x", "javascript:alert(1)", "/\\evil", 42])(
    "refuse un chemin hors de CoGes (%s) : la liste des alertes à la place",
    async (url) => {
      const sw = environment();
      await sw.push({ title: "Alerte", url });
      expect(sw.shown[0]!.options.data).toEqual({ url: "/notifications" });
    },
  );

  it("un message illisible montre quand même une alerte générique", async () => {
    const sw = environment();
    await sw.push("pas du json");
    await sw.push(undefined);
    expect(sw.shown.map((item) => item.title)).toEqual([
      "Nouvelle alerte dans CoGes",
      "Nouvelle alerte dans CoGes",
    ]);
  });
});

describe("notificationclick", () => {
  it("ramène l'onglet ouvert sur l'écran de l'alerte", async () => {
    const sw = environment([{ url: "https://coges.test/dashboard" }]);
    await sw.click("/sales/42");
    expect(sw.navigated).toEqual(["https://coges.test/sales/42"]);
    expect(sw.opened).toEqual([]);
  });

  it("ouvre CoGes s'il n'est pas ouvert", async () => {
    const sw = environment([{ url: "https://autre.example/" }]);
    await sw.click("/finance/collect?customer=abc");
    expect(sw.opened).toEqual(["https://coges.test/finance/collect?customer=abc"]);
  });

  it("ne mène jamais hors de CoGes", async () => {
    const sw = environment();
    await sw.click("https://evil.example/");
    expect(sw.opened).toEqual(["https://coges.test/notifications"]);
  });
});
