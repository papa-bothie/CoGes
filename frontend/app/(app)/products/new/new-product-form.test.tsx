import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import { renderWithClient } from "@/test/render";

import { marginLine, NewProductForm } from "./new-product-form";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/hooks/use-me", () => ({
  useCompanyLocale: () => ({ currency: "XOF", timeZone: "Africa/Dakar" }),
}));
vi.mock("@/hooks/use-permission", () => ({ usePermission: () => true }));
vi.mock("@/lib/api/client", () => ({
  api: {
    GET: vi.fn(async () => ({
      items: [
        { id: "cereales", name: "Céréales", parent_id: null },
        { id: "huiles", name: "Huiles", parent_id: null },
      ],
      page: 1,
      page_size: 100,
      total: 2,
    })),
    POST: vi.fn(async () => ({ product: { id: "riz" }, opening_movement: null })),
    PATCH: vi.fn(),
  },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

beforeEach(() => vi.mocked(api.POST).mockClear());

describe("marge en direct", () => {
  it("dit ce qu'on gagne, ou ce qu'on perd", () => {
    expect(marginLine("15500", "14000", "sac", "XOF")).toEqual({
      text: "Vous gagnez 1 500 F sur chaque sac",
      tone: "gain",
    });
    expect(marginLine("900", "1000", "paquet", "XOF").text).toBe(
      "Attention : vous perdez 100 F à chaque vente",
    );
    expect(marginLine("900", "900", "piece", "XOF").text).toBe(
      "Vous ne gagnez rien sur cet article",
    );
    expect(marginLine("900", "", "piece", "XOF").text).toBe(
      "Indiquez les deux prix pour voir ce que vous gagnez",
    );
  });
});

describe("Nouvel article", { timeout: 15_000 }, () => {
  it("ne demande ni référence, ni TVA, ni suivi du stock", async () => {
    renderWithClient(<NewProductForm />);
    expect(screen.queryByText(/SKU|Référence|TVA|Suivi/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Scanner le code-barres" })).toBeInTheDocument();
  });

  it("crée l'article et son stock d'ouverture en un envoi", async () => {
    renderWithClient(<NewProductForm />);
    await userEvent.type(screen.getByLabelText("Nom de l'article"), "Riz brisé 25 kg");
    await userEvent.type(screen.getByLabelText("Prix de vente (F)"), "15500");
    await userEvent.type(screen.getByLabelText("Prix d'achat (F)"), "14000");
    await userEvent.click(screen.getByRole("button", { name: "Sac" }));
    await userEvent.click(await screen.findByRole("button", { name: "Céréales" }));
    const [stock, warn] = screen.getAllByLabelText("Quantité : Riz brisé 25 kg");
    await userEvent.clear(stock!);
    await userEvent.type(stock!, "12");
    await userEvent.type(warn!, "3");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer l'article" }));

    expect(api.POST).toHaveBeenCalledWith("/api/v1/inventory/products", {
      body: {
        name: "Riz brisé 25 kg",
        unit: "sac",
        unit_price: "15500",
        cost_price: "14000",
        category_id: "cereales",
        barcode: null,
        is_stock_tracked: true,
        default_tax_rate: "0",
        opening_qty: "12",
        reorder_point: "3",
      },
    });
  });

  it("garde le bouton grisé tant qu'un stock n'a pas de prix d'achat", async () => {
    renderWithClient(<NewProductForm />);
    await userEvent.type(screen.getByLabelText("Nom de l'article"), "Savon");
    await userEvent.type(screen.getByLabelText("Prix de vente (F)"), "300");
    const [stock] = screen.getAllByLabelText("Quantité : Savon");
    await userEvent.clear(stock!);
    await userEvent.type(stock!, "10");
    expect(screen.getByRole("button", { name: "Enregistrer l'article" })).toBeDisabled();
    expect(screen.getByText("Indiquez le prix d'achat pour compter ce stock")).toBeInTheDocument();
  });
});
