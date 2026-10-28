import { afterEach, describe, expect, it, vi } from "vitest";

import { THEME_BOOT_SCRIPT, THEME_STORAGE_KEY } from "./theme";

/** Le script en ligne du layout, joué tel qu'il part dans le HTML. */
function boot(): void {
  new Function(THEME_BOOT_SCRIPT)();
}

describe("script de démarrage du thème", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    window.localStorage.clear();
    document.documentElement.dataset.theme = "light";
    document.documentElement.style.colorScheme = "";
  });

  it("garde le clair sans choix mémorisé, quel que soit le système", () => {
    // jsdom n'a pas matchMedia : un système en sombre est simulé.
    vi.stubGlobal("matchMedia", () => ({ matches: true }) as MediaQueryList);
    boot();
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("pose le sombre mémorisé avant l'affichage", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    boot();
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.style.colorScheme).toBe("dark");
  });

  it("ignore une valeur inconnue et un stockage qui refuse", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "system");
    boot();
    expect(document.documentElement.dataset.theme).toBe("light");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(boot).not.toThrow();
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("a une clé propre à l'administration", () => {
    expect(THEME_STORAGE_KEY).toBe("coges-admin:theme");
  });
});
