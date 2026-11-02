import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * En-têtes de sécurité du build de production (prompt 33, ADR 0106) : la caméra permise à la
 * même origine pour le scan du code-barres, le moteur WebAssembly du lecteur autorisé par
 * `'wasm-unsafe-eval'`, jamais `'unsafe-eval'`, et aucune connexion hors de l'origine.
 */
async function productionHeaders(): Promise<Record<string, string>> {
  vi.resetModules();
  vi.stubEnv("NODE_ENV", "production");
  const config = (await import("../next.config")).default;
  const rules = await config.headers!();
  return Object.fromEntries(rules[0]!.headers.map(({ key, value }) => [key, value]));
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("en-têtes du build de production", () => {
  it("permet la caméra à la même origine, garde micro et position fermés", async () => {
    expect((await productionHeaders())["Permissions-Policy"]).toBe(
      "camera=(self), microphone=(), geolocation=()",
    );
  });

  it("autorise le moteur WebAssembly sans ouvrir eval", async () => {
    const csp = (await productionHeaders())["Content-Security-Policy"]!;
    const script = csp.split("; ").find((directive) => directive.startsWith("script-src "));
    expect(script).toBe("script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'");
    expect(csp).not.toContain("'unsafe-eval'");
    expect(csp).toContain("connect-src 'self';");
  });
});
