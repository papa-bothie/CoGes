import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import { renderWithClient } from "@/test/render";

import { StockCorrectionDialog } from "./stock-correction-dialog";

const line = (id: string, name: string, unit: string, qty: string, status: string) => ({
  product_id: id,
  sku: id,
  name,
  unit,
  category_id: null,
  category_name: null,
  qty_on_hand: qty,
  avg_cost: "14000.0000",
  stock_value: "0.00",
  reorder_point: "3.000",
  status,
  last_movement_at: null,
});

vi.mock("@/lib/api/client", () => ({
  api: {
    // Ordre du serveur : ruptures et seuils bas en tête.
    GET: vi.fn(async () => ({
      items: [
        line("riz", "Riz brisé 25 kg", "sac", "2.000", "low"),
        line("savon", "Savon Madar", "piece", "60.000", "ok"),
      ],
      page: 1,
      page_size: 100,
      total: 2,
    })),
    POST: vi.fn(async () => ({ id: "m1" })),
    PATCH: vi.fn(),
  },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

beforeEach(() => vi.mocked(api.POST).mockClear());

describe("Corriger le stock", { timeout: 15_000 }, () => {
  it("met les articles bientôt épuisés en tête, avec leur quantité", async () => {
    renderWithClient(<StockCorrectionDialog open onOpenChange={() => {}} />);
    const riz = await screen.findByRole("button", { name: /Riz brisé 25 kg/ });
    expect(riz).toHaveTextContent("Plus que 2 sacs");
    expect(screen.getByRole("button", { name: /Savon Madar/ })).toHaveTextContent("60 pièces");
  });

  it("corrige en moins avec une raison en tuile, sans rien écrire", async () => {
    renderWithClient(<StockCorrectionDialog open onOpenChange={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: /Riz brisé 25 kg/ }));
    expect(screen.getByText("2 sacs")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "Moins" }));
    expect(screen.getByRole("status")).toHaveTextContent("Après : 1 sac");

    const submit = screen.getByRole("button", { name: "Valider la correction" });
    expect(submit).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: "Abîmé ou cassé" }));
    await userEvent.click(submit);

    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/inventory/movements",
      expect.objectContaining({
        body: { product_id: "riz", reason_code: "damaged", qty_delta: "-1" },
      }),
    );
  });

  it("propose les raisons d'un ajout, et refuse de retirer plus qu'il n'y a", async () => {
    renderWithClient(<StockCorrectionDialog open onOpenChange={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: /Riz brisé 25 kg/ }));
    await userEvent.click(screen.getByRole("radio", { name: "Plus" }));
    expect(screen.getByRole("radio", { name: "Retrouvé" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Cadeau du fournisseur" })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Périmé" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("radio", { name: "Moins" }));
    const field = screen.getByLabelText("Quantité : Riz brisé 25 kg");
    await userEvent.clear(field);
    await userEvent.type(field, "5");
    expect(screen.getByText("Le logiciel n'en compte que 2 sacs")).toBeInTheDocument();
  });
});
