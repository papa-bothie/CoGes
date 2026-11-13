import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { BRAND_COLORS } from "@/lib/brand-colors";

import { ALWAYS_LIGHT_VIEWPORT, isAlwaysLight } from "./always-light";

/** Pages d'entrée toujours claires (prompt 39, bloc C, ADR 0123) : la liste exacte. */
describe("pages toujours claires", () => {
  it.each([
    "/",
    "/login",
    "/inscription",
    "/verification",
    "/verification/abc-def_123",
    "/conditions",
    "/confidentialite",
  ])("%s est claire", (path) => {
    expect(isAlwaysLight(path)).toBe(true);
  });

  it.each([
    "/dashboard",
    "/parametres",
    "/settings",
    "/sales/new",
    "/acceptation",
    "/password",
    "/support",
    "/account/password",
    "/hors-ligne",
    "/loginx",
    "/login/autre",
    "/inscriptions",
    "/verification/a/b",
    "/conditions/x",
    "",
    null,
  ])("%s suit le thème de la personne", (path) => {
    expect(isAlwaysLight(path)).toBe(false);
  });

  it("couleur claire et barre du navigateur au fond papier", () => {
    expect(ALWAYS_LIGHT_VIEWPORT).toEqual({
      colorScheme: "light",
      themeColor: BRAND_COLORS.background,
    });
  });
});

describe("chaque page toujours claire déclare color-scheme et theme-color", () => {
  const ROOT = join(__dirname, "..", "..");
  it.each([
    "app/(vitrine)/page.tsx",
    "app/(vitrine)/conditions/page.tsx",
    "app/(vitrine)/confidentialite/page.tsx",
    "app/(auth)/login/page.tsx",
    "app/(auth)/inscription/page.tsx",
    "app/(auth)/verification/page.tsx",
    "app/(auth)/verification/[jeton]/page.tsx",
  ])("%s", (file) => {
    expect(readFileSync(join(ROOT, file), "utf8")).toContain(
      "export const viewport = ALWAYS_LIGHT_VIEWPORT;",
    );
  });
});
