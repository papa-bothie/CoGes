import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StatusDialog } from "./status-dialog";

describe("confirmation de suspension", () => {
  it("rien ne part sans raison", async () => {
    const onConfirm = vi.fn(async () => undefined);
    render(
      <StatusDialog
        companyName="Boutique Diallo"
        target="suspended"
        open
        onCancel={() => undefined}
        onConfirm={onConfirm}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Suspendre" }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Donnez la raison");
  });

  it("confirme avec la raison donnée", async () => {
    const onConfirm = vi.fn(async () => undefined);
    render(
      <StatusDialog
        companyName="Boutique Diallo"
        target="suspended"
        open
        onCancel={() => undefined}
        onConfirm={onConfirm}
      />,
    );
    expect(screen.getByText(/Personne de cette entreprise/)).toBeVisible();
    await userEvent.type(screen.getByLabelText("Raison"), "Impayé depuis deux mois");
    await userEvent.click(screen.getByRole("button", { name: "Suspendre" }));
    expect(onConfirm).toHaveBeenCalledWith("Impayé depuis deux mois");
  });

  it("annuler n'appelle rien", async () => {
    const onConfirm = vi.fn(async () => undefined);
    const onCancel = vi.fn();
    render(
      <StatusDialog
        companyName="Boutique Diallo"
        target="active"
        open
        onCancel={onCancel}
        onConfirm={onConfirm}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Annuler" }));
    expect(onCancel).toHaveBeenCalledOnce();
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
