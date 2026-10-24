import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { logout, refreshSession } from "./session";
import {
  acceptSupportFragment,
  endSupportSession,
  isSupportMode,
  restoreSupportToken,
} from "./support";
import { tokenStore } from "./token-store";

const NOW = 1_800_000_000_000;

beforeEach(() => {
  window.history.replaceState(null, "", "/support#token=jeton-support&expires_in=7200");
});

afterEach(() => {
  sessionStorage.clear();
  tokenStore.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("accès support (ADR 0092)", () => {
  it("garde le jeton pour l'onglet et efface aussitôt le fragment de l'adresse", () => {
    expect(acceptSupportFragment(window.location.hash, NOW)).toBe(true);
    expect(window.location.hash).toBe("");
    expect(window.location.pathname).toBe("/support");
    expect(isSupportMode()).toBe(true);
    expect(tokenStore.get()).toBe("jeton-support");
  });

  it("refuse un fragment incomplet, et l'efface quand même", () => {
    window.history.replaceState(null, "", "/support#token=jeton-support");
    expect(acceptSupportFragment(window.location.hash, NOW)).toBe(false);
    expect(window.location.hash).toBe("");
    expect(isSupportMode()).toBe(false);
  });

  it("reprend le jeton après un rechargement, jamais au-delà de son heure", () => {
    acceptSupportFragment(window.location.hash, NOW);
    tokenStore.clear();
    expect(restoreSupportToken(NOW + 60_000)).toBe(true);
    expect(tokenStore.get()).toBe("jeton-support");
    expect(restoreSupportToken(NOW + 7_200_000)).toBe(false);
  });

  it("ne touche jamais au cookie d'une vraie session", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    acceptSupportFragment(window.location.hash);
    tokenStore.clear();
    expect(await refreshSession()).toBe("ok");
    window.history.replaceState(null, "", "/support/termine"); // déjà sur l'écran de fin
    await logout();
    expect(fetch).not.toHaveBeenCalled();
    expect(isSupportMode()).toBe(false);
  });

  it("à la fin, oublie le jeton et montre l'écran de fin", () => {
    const assign = vi.fn();
    acceptSupportFragment(window.location.hash, NOW);
    endSupportSession(assign);
    expect(isSupportMode()).toBe(false);
    expect(tokenStore.get()).toBeNull();
    expect(assign).toHaveBeenCalledWith(`${window.location.origin}/support/termine`);
  });
});
