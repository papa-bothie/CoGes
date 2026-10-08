import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import type { Schemas } from "@/lib/api/schema";
import { renderWithClient } from "@/test/render";

import { ExpenseDialog } from "./expense-dialog";

vi.mock("@/hooks/use-me", () => ({
  useCompanyLocale: () => ({ currency: "XOF", timeZone: "Africa/Dakar" }),
}));
vi.mock("@/hooks/use-permission", () => ({ usePermission: () => true }));
vi.mock("@/lib/api/client", () => ({
  api: { GET: vi.fn(), POST: vi.fn(async () => ({ id: "e1" })), PATCH: vi.fn() },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

const CATEGORIES = [
  { id: "loyer", name: "Loyer", kind: "fixed" },
  { id: "elec", name: "Électricité", kind: "fixed" },
] as unknown as Schemas["ExpenseCategoryRead"][];

describe("Nouvelle dépense", { timeout: 15_000 }, () => {
  it("pour quoi, combien, quand, payé avec : rien à écrire", async () => {
    renderWithClient(<ExpenseDialog open onOpenChange={() => {}} categories={CATEGORIES} />);
    expect(screen.queryByText(/Libellé|Référence|Note|Fournisseur/)).not.toBeInTheDocument();

    const save = screen.getByRole("button", { name: "Enregistrer la dépense" });
    expect(save).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: "Électricité" }));
    for (const key of ["3", "5", "000"]) {
      await userEvent.click(screen.getByRole("button", { name: key }));
    }
    await userEvent.click(screen.getByRole("button", { name: "Orange Money" }));
    await userEvent.click(save);

    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/expenses",
      expect.objectContaining({
        body: expect.objectContaining({
          category_id: "elec",
          label: "Électricité",
          amount: "35000",
          payment: { method: "orange_money" },
        }),
      }),
    );
  });
});
