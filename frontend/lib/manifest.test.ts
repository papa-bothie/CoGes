import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import manifest from "@/app/manifest";

import { BRAND_COLORS } from "./brand-colors";

const PUBLIC = join(__dirname, "..", "public");

/** Largeur et hauteur d'un PNG, lues dans son en-tête IHDR. */
function pngSize(path: string): string {
  const bytes = readFileSync(path);
  return `${bytes.readUInt32BE(16)}x${bytes.readUInt32BE(20)}`;
}

describe("manifeste de l'application (ADR 0102)", () => {
  const value = manifest();

  it("a les champs d'une application installable", () => {
    expect(value).toMatchObject({
      name: "CoGes",
      short_name: "CoGes",
      lang: "fr",
      display: "standalone",
      start_url: "/dashboard",
      scope: "/",
    });
    expect(value.theme_color).toBe(BRAND_COLORS.theme);
    expect(value.background_color).toBe(BRAND_COLORS.background);
  });

  it("déclare des icônes qui existent, aux bonnes tailles, dont une masquable", () => {
    const icons = value.icons ?? [];
    for (const icon of icons) {
      const path = join(PUBLIC, icon.src);
      expect(existsSync(path), icon.src).toBe(true);
      expect(pngSize(path), icon.src).toBe(icon.sizes);
    }
    expect(icons.map((icon) => icon.sizes)).toEqual(expect.arrayContaining(["192x192", "512x512"]));
    expect(icons.some((icon) => icon.purpose === "maskable")).toBe(true);
  });
});
