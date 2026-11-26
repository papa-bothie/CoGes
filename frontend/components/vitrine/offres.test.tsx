import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import offres from "@/content/offres.json";
import { formatAmount } from "@/lib/format/money";
import { BUSINESS_EXTRAS, FEATURE_LABELS, PRO } from "@/lib/offres";

import { NosOffres } from "./offres";

/** Tout montant « 4 900 F » affiché dans la section. */
function shownAmounts(container: HTMLElement): string[] {
  return [...(container.textContent ?? "").matchAll(/\d[\d  ]* F\b/g)].map((m) => m[0]);
}

describe("vitrine : Nos offres (prompt 41, B5)", () => {
  it("deux cartes, les montants de la source seulement, mois et an", () => {
    const { container } = render(<NosOffres />);
    const expected = offres.plans
      .filter((plan) => plan.monthly !== null)
      .flatMap((plan) => [formatAmount(String(plan.monthly)), formatAmount(String(plan.annual))]);
    expect(shownAmounts(container).sort()).toEqual([...expected].sort());
    expect(screen.getByRole("heading", { name: "CoGes Pro" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "CoGes Business" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Premium/ })).toBeNull();
    expect(
      screen.getByText("Plus de 7 personnes ? Premium, sur devis : écrivez-nous"),
    ).toBeInTheDocument();
    expect(screen.getByText("30 jours d'essai gratuit sur Pro")).toBeInTheDocument();
  });

  it("la bascule est un groupe de deux boutons radio, « Par mois » d'abord", () => {
    render(<NosOffres />);
    const group = screen.getByRole("group", { name: "Durée du paiement" });
    const month = within(group).getByRole("radio", { name: "Par mois" });
    const year = within(group).getByRole("radio", { name: "Par an (-10 %)" });
    expect(month).toBeChecked();
    fireEvent.click(year);
    expect(year).toBeChecked();
  });

  it("« 10 % » ne paraît que dans la bascule", () => {
    const { container } = render(<NosOffres />);
    const group = screen.getByRole("group", { name: "Durée du paiement" });
    const outside = (container.textContent ?? "").replace(group.textContent ?? "", "");
    expect(outside).not.toMatch(/\d+ ?%/);
  });

  it("chaque carte liste les fonctions de son offre", () => {
    render(<NosOffres />);
    const pro = screen.getByRole("heading", { name: "CoGes Pro" }).closest("li")!;
    for (const code of PRO.features) {
      expect(within(pro).getByText(FEATURE_LABELS[code])).toBeInTheDocument();
    }
    const business = screen.getByRole("heading", { name: "CoGes Business" }).closest("li")!;
    for (const code of BUSINESS_EXTRAS) {
      expect(within(business).getByText(FEATURE_LABELS[code])).toBeInTheDocument();
    }
    expect(within(business).getByText("Support prioritaire")).toBeInTheDocument();
    expect(within(business).queryByText(/24/)).toBeNull();
  });
});
