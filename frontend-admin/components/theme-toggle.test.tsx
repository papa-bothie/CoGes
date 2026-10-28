import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { THEME_STORAGE_KEY } from "@/lib/theme";

import { ThemeToggle } from "./theme-toggle";

/** Le script du layout pose l'attribut avant l'affichage ; ici, on le simule. */
function bootTheme(theme: "light" | "dark" | null): void {
  document.documentElement.dataset.theme = theme ?? "light";
}

describe("ThemeToggle", () => {
  beforeEach(() => {
    window.localStorage.clear();
    bootTheme(null);
  });
  afterEach(() => {
    vi.restoreAllMocks();
    bootTheme(null);
  });

  it("commence en clair, sans rien de mémorisé", () => {
    render(<ThemeToggle />);
    const button = screen.getByRole("button", { name: "Passer en mode sombre" });
    expect(button).toHaveAttribute("aria-pressed", "false");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("bascule en sombre puis revient au clair, et mémorise le choix", async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);
    await user.click(screen.getByRole("button", { name: "Passer en mode sombre" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    const back = screen.getByRole("button", { name: "Passer en mode clair" });
    expect(back).toHaveAttribute("aria-pressed", "true");

    await user.click(back);
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(screen.getByRole("button", { name: "Passer en mode sombre" })).toBeInTheDocument();
  });

  it("reprend le sombre déjà posé par le script du layout", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    bootTheme("dark");
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: "Passer en mode clair" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("marche sans stockage : la bascule change l'écran, rien ne casse", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    const user = userEvent.setup();
    render(<ThemeToggle />);
    await user.click(screen.getByRole("button", { name: "Passer en mode sombre" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("suit le choix fait dans un onglet voisin", () => {
    render(<ThemeToggle />);
    act(() => {
      window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
      window.dispatchEvent(
        new StorageEvent("storage", { key: THEME_STORAGE_KEY, newValue: "dark" }),
      );
    });
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(screen.getByRole("button", { name: "Passer en mode clair" })).toBeInTheDocument();
  });

  it("ignore la clé du thème de l'application des commerçants", () => {
    render(<ThemeToggle />);
    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key: "theme", newValue: "dark" }));
    });
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
