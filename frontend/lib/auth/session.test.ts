import { afterEach, describe, expect, it, vi } from "vitest";

import { refreshSession, SESSION_MARKER } from "./session";
import { tokenStore } from "./token-store";

afterEach(() => {
  vi.unstubAllGlobals();
  tokenStore.clear();
  document.cookie = `${SESSION_MARKER}=; Path=/; Max-Age=0`;
});

describe("refreshSession", () => {
  it("mutualise les rafraîchissements concurrents en une seule requête", async () => {
    const fetch = vi.fn(async () => {
      await new Promise((resolve) => setTimeout(resolve, 5));
      return new Response(JSON.stringify({ access_token: "a1", expires_in: 900 }), {
        status: 200,
      });
    });
    vi.stubGlobal("fetch", fetch);

    const outcomes = await Promise.all([refreshSession(), refreshSession(), refreshSession()]);

    expect(outcomes).toEqual(["ok", "ok", "ok"]);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(tokenStore.get()).toBe("a1");
    expect(document.cookie).toContain(`${SESSION_MARKER}=1`);
  });

  it("distingue un refus (401) d'une panne", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("{}", { status: 401 })),
    );
    expect(await refreshSession()).toBe("unauthenticated");

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("{}", { status: 503 })),
    );
    expect(await refreshSession()).toBe("unavailable");

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("network");
      }),
    );
    expect(await refreshSession()).toBe("unavailable");
  });
});

describe("tokenStore", () => {
  it("considère un jeton proche de l'expiration comme périmé", () => {
    tokenStore.set("t", 900, 0);
    expect(tokenStore.fresh(0)).toBe("t");
    expect(tokenStore.fresh(900_000 - 30_000)).toBeNull();
  });
});

describe("onLogoutElsewhere", () => {
  it("n'entend pas les annonces de son propre onglet", async () => {
    const { expireSession, onLogoutElsewhere } = await import("./session");
    const handler = vi.fn();
    const stop = onLogoutElsewhere(handler);
    const other = new BroadcastChannel("coges-auth");
    const heard = new Promise((resolve) => (other.onmessage = resolve));

    expireSession();
    await heard; // l'autre onglet, lui, reçoit l'annonce
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(handler).not.toHaveBeenCalled();
    stop();
    other.close();
  });
});
