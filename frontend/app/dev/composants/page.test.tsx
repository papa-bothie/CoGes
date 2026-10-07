import { afterEach, describe, expect, it, vi } from "vitest";

import ComponentsPage from "./page";

describe("vitrine /dev/composants", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("n'existe pas en production (404)", () => {
    vi.stubEnv("NODE_ENV", "production");
    expect(() => ComponentsPage()).toThrow(/NEXT_HTTP_ERROR_FALLBACK;404/);
  });

  it("s'affiche en développement", () => {
    vi.stubEnv("NODE_ENV", "development");
    expect(ComponentsPage()).toBeTruthy();
  });
});
