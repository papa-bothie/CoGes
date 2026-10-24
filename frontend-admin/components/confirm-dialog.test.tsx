import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ConfirmDialog, type ConfirmRequest } from "./confirm-dialog";

function Harness({
  request,
}: {
  request: Omit<ConfirmRequest, "onConfirm"> & { onConfirm: (reason: string) => Promise<void> };
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Ouvrir
      </button>
      <ConfirmDialog request={open ? request : null} onClose={() => setOpen(false)} />
    </>
  );
}

const SUSPEND = {
  title: "Suspendre Moussa B. ?",
  consequence: "Moussa B. ne pourra plus se connecter.",
  confirmLabel: "Suspendre Moussa B.",
  destructive: true,
  requireReason: true,
};

describe("confirmation des actions sensibles", () => {
  it("nomme la cible, préfocalise « Annuler » et exige la raison", async () => {
    const onConfirm = vi.fn(async () => undefined);
    render(<Harness request={{ ...SUSPEND, onConfirm }} />);
    await userEvent.click(screen.getByRole("button", { name: "Ouvrir" }));
    expect(screen.getByRole("heading", { name: "Suspendre Moussa B. ?" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Annuler" })).toHaveFocus();
    await userEvent.click(screen.getByRole("button", { name: "Suspendre Moussa B." }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Donnez la raison");
    await userEvent.type(screen.getByLabelText("Raison"), "Départ de l'équipe");
    await userEvent.click(screen.getByRole("button", { name: "Suspendre Moussa B." }));
    expect(onConfirm).toHaveBeenCalledWith("Départ de l'équipe");
  });

  it("Échap annule et rend le focus au bouton d'origine", async () => {
    const onConfirm = vi.fn(async () => undefined);
    render(<Harness request={{ ...SUSPEND, onConfirm }} />);
    const opener = screen.getByRole("button", { name: "Ouvrir" });
    await userEvent.click(opener);
    screen.getByRole("dialog").dispatchEvent(new Event("cancel", { cancelable: true }));
    await screen.findByRole("button", { name: "Ouvrir" });
    expect(screen.queryByRole("heading", { name: "Suspendre Moussa B. ?" })).toBeNull();
    expect(opener).toHaveFocus();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("un double clic n'envoie qu'une fois", async () => {
    let finish: () => void = () => undefined;
    const onConfirm = vi.fn(() => new Promise<void>((resolve) => (finish = resolve)));
    render(
      <Harness request={{ ...SUSPEND, requireReason: false, destructive: false, onConfirm }} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Ouvrir" }));
    const confirm = screen.getByRole("button", { name: "Suspendre Moussa B." });
    await userEvent.dblClick(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Un instant…" })).toBeDisabled();
    finish();
  });

  it("une erreur reste dans la fenêtre, lisible", async () => {
    const onConfirm = vi.fn(async () => {
      throw new Error("Il doit toujours rester un administrateur actif.");
    });
    render(<Harness request={{ ...SUSPEND, requireReason: false, onConfirm }} />);
    await userEvent.click(screen.getByRole("button", { name: "Ouvrir" }));
    await userEvent.click(screen.getByRole("button", { name: "Suspendre Moussa B." }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Il doit toujours rester un administrateur actif.",
    );
    expect(screen.getByRole("button", { name: "Suspendre Moussa B." })).toBeEnabled();
  });
});
