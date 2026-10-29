import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Identifiant de build (prompt 32, P4) : vide, le worker serait le même d'un build à l'autre et
 * aucune mise à jour ne serait jamais repérée. L'image de production refuse de se construire
 * sans lui, et chaque construction de l'image le passe.
 */
const read = (...path: string[]) => readFileSync(join(__dirname, "..", ...path), "utf8");

describe("identifiant de build de l'image du front", () => {
  it("le Dockerfile échoue avant le build si NEXT_DEPLOYMENT_ID est vide", () => {
    const dockerfile = read("Dockerfile");
    const guard = dockerfile.indexOf('test -n "$NEXT_DEPLOYMENT_ID"');
    expect(guard).toBeGreaterThan(-1);
    expect(guard).toBeLessThan(dockerfile.indexOf("pnpm build"));
  });

  it.each([
    ["deploy.yml", /NEXT_DEPLOYMENT_ID=\$\{\{ steps\.version\.outputs\.version \}\}/],
    ["ci.yml", /NEXT_DEPLOYMENT_ID=ci-\$\{\{ github\.sha \}\}/],
  ])("%s passe l'identifiant à l'image du front", (workflow, pattern) => {
    expect(read("..", ".github", "workflows", workflow)).toMatch(pattern);
  });
});
