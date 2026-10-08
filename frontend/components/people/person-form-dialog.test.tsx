import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import { renderWithClient } from "@/test/render";

import { PersonFormDialog } from "./person-form-dialog";

vi.mock("@/lib/api/client", () => ({
  api: {
    GET: vi.fn(),
    POST: vi.fn(async (_path: string, init?: { body: { name: string } }) => ({
      id: "p1",
      ...init?.body,
    })),
    PATCH: vi.fn(),
  },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

beforeEach(() => vi.mocked(api.POST).mockClear());

describe("Ajouter une personne", { timeout: 15_000 }, () => {
  it("ne demande que le nom et le téléphone, au format du Sénégal", async () => {
    renderWithClient(<PersonFormDialog open onOpenChange={() => {}} />);
    expect(screen.queryByText(/Code/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Encours/)).not.toBeInTheDocument();
    expect(screen.getByText("+221")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Nom du client"), "Aminata Sow");
    await userEvent.type(screen.getByLabelText("Téléphone"), "776559021");
    expect(screen.getByLabelText("Téléphone")).toHaveValue("77 655 90 21");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer le client" }));

    expect(api.POST).toHaveBeenCalledWith("/api/v1/customers", {
      body: { name: "Aminata Sow", phone: "77 655 90 21", email: null },
    });
  });

  it("enregistre un fournisseur, sans e-mail ni délai", async () => {
    renderWithClient(<PersonFormDialog open onOpenChange={() => {}} />);
    await userEvent.click(screen.getByRole("radio", { name: "Un fournisseur" }));
    await userEvent.type(screen.getByLabelText("Nom du fournisseur"), "Grossiste Sandaga");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer le fournisseur" }));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/suppliers", {
      body: { name: "Grossiste Sandaga", phone: null },
    });
  });

  it("refuse un numéro incomplet", async () => {
    renderWithClient(<PersonFormDialog open onOpenChange={() => {}} />);
    await userEvent.type(screen.getByLabelText("Nom du client"), "Awa");
    await userEvent.type(screen.getByLabelText("Téléphone"), "7765");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer le client" }));
    expect(screen.getByText("Le numéro a 9 chiffres : 77 000 00 00")).toBeInTheDocument();
    expect(api.POST).not.toHaveBeenCalled();
  });
});
