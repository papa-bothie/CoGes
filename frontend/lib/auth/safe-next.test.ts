import { describe, expect, it } from "vitest";

import { DEFAULT_NEXT, safeNext } from "./safe-next";

const ORIGIN = "https://coges.example";

describe("safeNext", () => {
  it.each([
    ["//evil.example"],
    ["/\\evil.example"], // lu « //evil.example » par le navigateur
    ["\\\\evil.example"],
    ["/\t/evil.example"], // la tabulation est supprimée par le parseur d'URL
    ["/\n/evil.example"],
    ["https://evil.example"],
    ["https://coges.example.evil.example/dashboard"],
    ["javascript:alert(1)"],
    ["/.//evil.example"], // normalisé en « //evil.example », même origine
    ["/%2e//evil.example"],
    ["/login"],
    ["/login?next=/sales"],
    [""],
    [null],
    [undefined],
  ])("refuse %j", (next) => {
    expect(safeNext(next, ORIGIN)).toBe(DEFAULT_NEXT);
  });

  it("garde un vrai chemin interne avec ses paramètres et son ancre", () => {
    expect(safeNext("/sales?page=2&status=draft#liste", ORIGIN)).toBe(
      "/sales?page=2&status=draft#liste",
    );
  });

  it("accepte une URL absolue de la même origine, réduite à son chemin", () => {
    expect(safeNext("https://coges.example/products?page=3", ORIGIN)).toBe("/products?page=3");
  });

  it("laisse encodées les barres obliques encodées : la destination reste sur le site", () => {
    const next = safeNext("/%2F%2Fevil.example", ORIGIN);
    expect(next).toBe("/%2F%2Fevil.example");
    expect(new URL(next, ORIGIN).origin).toBe(ORIGIN);
  });

  it("normalise les segments relatifs sans quitter le site", () => {
    expect(safeNext("/sales/../products", ORIGIN)).toBe("/products");
  });
});
