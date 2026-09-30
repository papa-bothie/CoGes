import { describe, expect, it } from "vitest";

import { flattenTree, type Category } from "./categories";

const category = (id: string, name: string, parent_id: string | null = null): Category => ({
  id,
  name,
  parent_id,
  created_at: "2026-09-30T00:00:00Z",
});

describe("flattenTree", () => {
  it("range les enfants sous leur parent, par ordre alphabétique", () => {
    const tree = flattenTree([
      category("3", "Eaux", "1"),
      category("2", "Épicerie"),
      category("1", "Boissons"),
      category("4", "Jus", "1"),
    ]);
    expect(tree.map((node) => [node.path, node.depth])).toEqual([
      ["Boissons", 0],
      ["Boissons › Eaux", 1],
      ["Boissons › Jus", 1],
      ["Épicerie", 0],
    ]);
  });

  it("remonte à la racine une catégorie dont le parent est introuvable", () => {
    expect(flattenTree([category("1", "Orpheline", "absent")])[0]?.depth).toBe(0);
  });
});
