import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import { renderWithClient } from "@/test/render";

import { CategoriesView } from "./categories-view";

vi.mock("@/hooks/use-permission", () => ({
  usePermission: () => true,
  Can: ({ children }: { children: ReactNode }) => children,
}));
vi.mock("@/lib/api/client", () => ({
  api: {
    GET: vi.fn(async (path: string) =>
      path === "/api/v1/products/category-counts"
        ? { items: [{ category_id: "cereales", product_count: 8 }] }
        : {
            items: [
              { id: "cereales", name: "Céréales", parent_id: null, color: 1 },
              { id: "frais", name: "Produits frais", parent_id: null, color: 6 },
            ],
            page: 1,
            page_size: 100,
            total: 2,
          },
    ),
    POST: vi.fn(async () => ({ id: "boissons", name: "Boissons", parent_id: null, color: 3 })),
    PATCH: vi.fn(async () => ({})),
    DELETE: vi.fn(async () => undefined),
  },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

beforeEach(() => {
  vi.mocked(api.POST).mockClear();
  vi.mocked(api.PATCH).mockClear();
});

describe("Rayons", { timeout: 15_000 }, () => {
  it("compte les articles et ne laisse supprimer qu'un rayon vide", async () => {
    renderWithClient(<CategoriesView />);
    const list = await screen.findByRole("list", { name: "Rayons" });
    expect(await within(list).findByText("8 articles")).toBeInTheDocument();
    expect(within(list).getByText("Aucun article")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Supprimer Céréales" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Supprimer Produits frais" })).toBeEnabled();
  });

  it("ajoute un rayon avec la couleur choisie", async () => {
    renderWithClient(<CategoriesView />);
    const add = screen.getByRole("button", { name: "Ajouter" });
    expect(add).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Nouveau rayon"), "Boissons");
    await userEvent.click(screen.getByRole("radio", { name: "Bleu" }));
    await userEvent.click(add);
    expect(api.POST).toHaveBeenCalledWith("/api/v1/categories", {
      body: { name: "Boissons", color: 3 },
    });
  });

  it("renomme sur place", async () => {
    renderWithClient(<CategoriesView />);
    await userEvent.click(await screen.findByRole("button", { name: "Renommer Céréales" }));
    const field = screen.getByLabelText("Nouveau nom de Céréales");
    await userEvent.clear(field);
    await userEvent.type(field, "Riz et céréales{Enter}");
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/categories/{category_id}", {
      params: { path: { category_id: "cereales" } },
      body: { name: "Riz et céréales" },
    });
  });
});
