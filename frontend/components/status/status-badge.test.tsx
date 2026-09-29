import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SaleStatusBadge, StockStatusBadge } from "./status-badge";

describe("SaleStatusBadge", () => {
  it("dérive « Retournée » d'une vente confirmée qui porte un retour", () => {
    render(<SaleStatusBadge status="confirmed" hasReturns />);
    expect(screen.getByText("Retournée").dataset.variant).toBe("warning");
  });

  it("garde le statut de la base sinon", () => {
    render(
      <>
        <SaleStatusBadge status="confirmed" hasReturns={false} />
        <SaleStatusBadge status="draft" hasReturns={false} />
        <SaleStatusBadge status="cancelled" hasReturns />
      </>,
    );
    expect(screen.getByText("Confirmée").dataset.variant).toBe("info");
    expect(screen.getByText("Brouillon").dataset.variant).toBe("neutral");
    // Une vente annulée reste annulée, même si elle a connu un retour avant.
    expect(screen.getByText("Annulée").dataset.variant).toBe("danger");
  });
});

describe("StockStatusBadge", () => {
  it("traduit le statut calculé par l'API", () => {
    render(<StockStatusBadge status="out" />);
    expect(screen.getByText("Rupture").dataset.variant).toBe("danger");
  });
});
