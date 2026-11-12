import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  deviceLabel,
  disablePush,
  enablePush,
  isAppleMobile,
  keyBytes,
  pushState,
  stopPushAtLogout,
} from "./push";

const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 Version/18.1 Mobile/15E148 Safari/604.1";
const ANDROID =
  "Mozilla/5.0 (Linux; Android 15; SM-A556B) AppleWebKit/537.36 Chrome/141.0.0.0 Mobile Safari/537.36";
const IPAD_AS_MAC =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/18.1 Safari/605.1.15";

/** Un navigateur qui sait recevoir des notifications, avec son abonnement simulé. */
function browser({
  permission = "default" as NotificationPermission,
  answer = "granted" as NotificationPermission,
  subscribed = false,
  userAgent = ANDROID,
  touch = 5,
  standalone = false,
} = {}) {
  const unsubscribe = vi.fn(async () => true);
  const subscription = {
    endpoint: "https://fcm.googleapis.com/fcm/send/abc",
    toJSON: () => ({
      endpoint: "https://fcm.googleapis.com/fcm/send/abc",
      keys: { p256dh: "B".repeat(87), auth: "A".repeat(22) },
    }),
    unsubscribe,
  };
  let current = subscribed ? subscription : null;
  const subscribe = vi.fn(async () => {
    current = subscription;
    return subscription;
  });
  const pushManager = { getSubscription: async () => current, subscribe };
  const registration = { pushManager };
  const requestPermission = vi.fn(async () => answer);
  vi.stubGlobal("Notification", { permission, requestPermission });
  vi.stubGlobal("PushManager", class {});
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: { getRegistration: async () => registration, ready: Promise.resolve(registration) },
  });
  Object.defineProperty(navigator, "userAgent", { configurable: true, value: userAgent });
  Object.defineProperty(navigator, "maxTouchPoints", { configurable: true, value: touch });
  Object.defineProperty(navigator, "standalone", { configurable: true, value: standalone });
  window.matchMedia = vi.fn(() => ({ matches: standalone }) as MediaQueryList);
  return { subscribe, unsubscribe, requestPermission };
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(null, { status: 204 })),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  // @ts-expect-error -- remis comme dans jsdom : pas de service worker
  delete navigator.serviceWorker;
});

describe("ce que l'appareil sait faire", () => {
  it("reconnaît l'iPhone et l'iPad qui se dit Mac", () => {
    expect(isAppleMobile(IPHONE, 5)).toBe(true);
    expect(isAppleMobile(IPAD_AS_MAC, 5)).toBe(true);
    expect(isAppleMobile(IPAD_AS_MAC, 0)).toBe(false);
    expect(isAppleMobile(ANDROID, 5)).toBe(false);
  });

  it("nomme l'appareil en mots simples", () => {
    expect(deviceLabel(ANDROID, 5)).toBe("Téléphone Android");
    expect(deviceLabel(IPHONE, 5)).toBe("iPhone");
    expect(deviceLabel(IPAD_AS_MAC, 5)).toBe("iPad");
  });

  it("décode la clé publique du serveur (base64url, 65 octets)", () => {
    const key = "B" + "A".repeat(86);
    const bytes = keyBytes(key);
    expect(bytes).toHaveLength(65);
    expect(bytes[0]).toBe(4);
  });
});

describe("état", () => {
  it("sans clé du serveur : indisponible", async () => {
    browser();
    expect(await pushState(null)).toBe("unavailable");
  });

  it("iPhone dans Safari : installer d'abord ; installé : on peut activer", async () => {
    browser({ userAgent: IPHONE });
    expect(await pushState("cle")).toBe("needs-install");
    browser({ userAgent: IPHONE, standalone: true });
    expect(await pushState("cle")).toBe("off");
  });

  it("refusé : le dit, sans redemander", async () => {
    const { requestPermission } = browser({ permission: "denied" });
    expect(await pushState("cle")).toBe("denied");
    expect(requestPermission).not.toHaveBeenCalled();
  });

  it("navigateur sans notifications", async () => {
    expect(await pushState("cle")).toBe("unsupported");
  });

  it("abonné et autorisé : activé", async () => {
    browser({ permission: "granted", subscribed: true });
    expect(await pushState("cle")).toBe("on");
  });
});

describe("activer", () => {
  it("la permission n'est demandée qu'à l'appui, puis l'abonnement part au serveur", async () => {
    const { requestPermission, subscribe } = browser();
    expect(await pushState("B" + "A".repeat(86))).toBe("off");
    expect(requestPermission).not.toHaveBeenCalled();

    const send = vi.fn(async () => ({}));
    expect(await enablePush("B" + "A".repeat(86), send)).toBe("on");
    expect(requestPermission).toHaveBeenCalledTimes(1);
    expect(subscribe).toHaveBeenCalledWith(expect.objectContaining({ userVisibleOnly: true }));
    expect(send).toHaveBeenCalledWith({
      endpoint: "https://fcm.googleapis.com/fcm/send/abc",
      keys: { p256dh: "B".repeat(87), auth: "A".repeat(22) },
      device_label: "Téléphone Android",
    });
  });

  it("refus du navigateur : rien n'est envoyé", async () => {
    const { subscribe } = browser({ answer: "denied" });
    const send = vi.fn();
    expect(await enablePush("B" + "A".repeat(86), send)).toBe("denied");
    expect(subscribe).not.toHaveBeenCalled();
    expect(send).not.toHaveBeenCalled();
  });

  it("refus du serveur : le navigateur ne reste pas abonné", async () => {
    const { unsubscribe } = browser();
    await expect(
      enablePush("B" + "A".repeat(86), async () => {
        throw new Error("refusé");
      }),
    ).rejects.toThrow("refusé");
    expect(unsubscribe).toHaveBeenCalled();
  });
});

describe("désactiver et se déconnecter", () => {
  it("« Désactiver » : le serveur d'abord, puis le navigateur", async () => {
    const { unsubscribe } = browser({ permission: "granted", subscribed: true });
    const remove = vi.fn(async () => undefined);
    await disablePush(remove);
    expect(remove).toHaveBeenCalledWith("https://fcm.googleapis.com/fcm/send/abc");
    expect(unsubscribe).toHaveBeenCalled();
  });

  it("la déconnexion arrête l'abonnement au serveur avec le jeton, puis dans le navigateur", async () => {
    const { unsubscribe } = browser({ permission: "granted", subscribed: true });
    await stopPushAtLogout("jeton");
    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/notifications/push/subscriptions/remove?logout=true");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer jeton");
    expect(JSON.parse(init.body as string)).toEqual({
      endpoint: "https://fcm.googleapis.com/fcm/send/abc",
    });
    expect(unsubscribe).toHaveBeenCalled();
  });

  it("une panne réseau n'empêche jamais la déconnexion", async () => {
    const { unsubscribe } = browser({ permission: "granted", subscribed: true });
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError("réseau"));
    await expect(stopPushAtLogout("jeton")).resolves.toBeUndefined();
    expect(unsubscribe).toHaveBeenCalled();
  });
});
