import { readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { describe, expect, it } from "vitest";

import { ROUTE_ACCESS, routePattern, routeRule } from "./access";
import { ADVICE_NAV, MAIN_NAV, SETTINGS_NAV } from "./navigation";

/** Chaque `page.tsx` de l'application connectée, en chemin d'URL (`/sales/[id]`). */
function pages(dir: string, root: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return pages(path, root);
    if (name !== "page.tsx") return [];
    const route = relative(root, dir)
      .split(sep)
      .filter((segment) => segment && !segment.startsWith("("))
      .join("/");
    return [`/${route}`];
  });
}

const APP = join(__dirname, "..", "app", "(app)");

describe("registre des écrans (ADR 0099)", () => {
  it("chaque page de l'application déclare le droit qu'elle exige", () => {
    const missing = pages(APP, APP).filter((route) => !(route in ROUTE_ACCESS));
    expect(missing, "pages sans droit déclaré dans lib/access.ts").toEqual([]);
  });

  it("reconnaît les paramètres et préfère un segment écrit en toutes lettres", () => {
    expect(routePattern("/sales/new")).toBe("/sales/new");
    expect(routePattern("/sales/1b2c")).toBe("/sales/[id]");
    expect(routePattern("/sales/1b2c/returns/new")).toBe("/sales/[id]/returns/new");
    expect(routePattern("/products/categories")).toBe("/products/categories");
    expect(routePattern("/finance/collect?customer=1")).toBe("/finance/collect");
    expect(routeRule("/inconnu")).toBeUndefined();
    expect(routeRule("/account/password")).toBeNull();
  });

  it("chaque entrée du menu s'ouvre sur le droit exact de son écran", () => {
    for (const item of [...MAIN_NAV, ADVICE_NAV, ...SETTINGS_NAV]) {
      for (const target of item.targets) {
        expect(target.permission, `${item.label} → ${target.href}`).toEqual(routeRule(target.href));
      }
    }
  });
});
