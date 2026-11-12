import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * Réécriture de `/api/v1` (correctif front-api-url) : figée au build. L'image du VPS sert
 * les deux piles, elle est construite sans `COGES_API_URL` et n'en émet aucune.
 */
async function rewritesWith(env: Record<string, string | undefined>) {
  vi.resetModules();
  for (const [key, value] of Object.entries(env)) vi.stubEnv(key, value);
  const { default: config } = await import("./next.config");
  return (await config.rewrites!()) as { destination: string }[];
}

describe("next.config rewrites", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("n'émet aucune réécriture dans un build de production sans COGES_API_URL", async () => {
    expect(await rewritesWith({ NODE_ENV: "production", COGES_API_URL: undefined })).toEqual([]);
  });

  it("vise COGES_API_URL quand elle est donnée", async () => {
    const [rule] = await rewritesWith({
      NODE_ENV: "production",
      COGES_API_URL: "http://localhost:8100/",
    });
    expect(rule?.destination.startsWith("http://localhost:8100/api/v1/")).toBe(true);
  });

  it("garde localhost:8000 en développement", async () => {
    const [rule] = await rewritesWith({ NODE_ENV: "development", COGES_API_URL: undefined });
    expect(rule?.destination.startsWith("http://localhost:8000/api/v1/")).toBe(true);
  });
});
