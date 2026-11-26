import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import offres from "@/content/offres.json";
import { formatAmount } from "@/lib/format/money";
import { BUSINESS_EXTRAS, FEATURE_LABELS, PRO, trialLink } from "@/lib/offres";

import { NosOffres } from "./offres";

/** Tout montant « 4 900 F » affiché dans la section. */
function shownAmounts(container: HTMLElement): string[] {
  return [...(container.textContent ?? "").matchAll(/\d[\d  ]* F\b/g)].map((m) => m[0]);
}

describe("vitrine : Nos offres (prompt 41, B5)", () => {
  it("Essai gratuit, Pro, Business, dans cet ordre ; les montants de la source seulement", () => {
    const { container } = render(<NosOffres signupEnabled />);
    const cards = container.querySelectorAll(":scope ul > li > h3");
    expect([...cards].map((node) => node.textContent)).toEqual([
      "Essai gratuit",
      "CoGes Pro",
      "CoGes Business",
    ]);
    const expected = offres.plans
      .filter((plan) => plan.monthly !== null)
      .flatMap((plan) => [formatAmount(String(plan.monthly)), formatAmount(String(plan.annual))]);
    expected.push(formatAmount(String(offres.trialPrice)));
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
    render(<NosOffres signupEnabled />);
    const group = screen.getByRole("group", { name: "Durée du paiement" });
    const month = within(group).getByRole("radio", { name: "Par mois" });
    const year = within(group).getByRole("radio", { name: "Par an (-10 %)" });
    expect(month).toBeChecked();
    fireEvent.click(year);
    expect(year).toBeChecked();
  });

  it("« 10 % » ne paraît que dans la bascule", () => {
    const { container } = render(<NosOffres signupEnabled />);
    const group = screen.getByRole("group", { name: "Durée du paiement" });
    const outside = (container.textContent ?? "").replace(group.textContent ?? "", "");
    expect(outside).not.toMatch(/\d+ ?%/);
  });

  it("chaque carte liste les fonctions de son offre", () => {
    render(<NosOffres signupEnabled />);
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

  it("« 0 F » ne paraît que dans la carte d'essai, tiré de la source partagée", () => {
    const { container } = render(<NosOffres signupEnabled />);
    const zero = formatAmount(String(offres.trialPrice));
    expect(zero).toBe("0\u00a0F");
    const trial = screen.getByRole("heading", { name: "Essai gratuit" }).closest("li")!;
    expect(trial.textContent).toContain(zero);
    const outside = (container.textContent ?? "").replace(trial.textContent ?? "", "");
    expect(outside).not.toMatch(/(^|[^\d\s\u00a0\u202f])0[\s\u00a0\u202f]F\b/);
    // Témoin : la même règle trouve bien le « 0 F » de la carte.
    expect(trial.textContent).toMatch(/(^|[^\d\s\u00a0\u202f])0[\s\u00a0\u202f]F\b/);
  });

  it("carte d'essai : 30 jours de la source, fonctions de Pro, aucun paiement", () => {
    render(<NosOffres signupEnabled />);
    const trial = screen.getByRole("heading", { name: "Essai gratuit" }).closest("li")!;
    expect(within(trial).getByText(`pendant ${offres.trialDays} jours`)).toBeInTheDocument();
    expect(within(trial).getByText("Toutes les fonctions de CoGes Pro")).toBeInTheDocument();
    expect(within(trial).getByText("Aucun paiement pour commencer")).toBeInTheDocument();
    expect(within(trial).getByText("Pour commencer")).toBeInTheDocument();
  });

  it("inscription ouverte : le bouton de l'essai mène à /inscription", () => {
    render(<NosOffres signupEnabled />);
    const trial = screen.getByRole("heading", { name: "Essai gratuit" }).closest("li")!;
    const button = within(trial).getByRole("link", { name: "Démarrer l'essai gratuit" });
    expect(button).toHaveAttribute("href", "/inscription");
  });

  it("inscription fermée : le bouton de l'essai ouvre WhatsApp, message prérempli", () => {
    render(<NosOffres signupEnabled={false} />);
    const trial = screen.getByRole("heading", { name: "Essai gratuit" }).closest("li")!;
    const button = within(trial).getByRole("link", { name: /Démarrer l'essai gratuit/ });
    expect(button).toHaveAttribute("href", trialLink());
    expect(decodeURIComponent(trialLink())).toContain("Je veux essayer CoGes gratuitement");
    expect(button).toHaveAttribute("target", "_blank");
  });

  it("la bascule annuelle ne touche pas la carte d'essai", () => {
    render(<NosOffres signupEnabled />);
    const trial = screen.getByRole("heading", { name: "Essai gratuit" }).closest("li")!;
    expect(trial.querySelector("[data-periode]")).toBeNull();
    const before = trial.innerHTML;
    fireEvent.click(screen.getByRole("radio", { name: "Par an (-10 %)" }));
    expect(trial.innerHTML).toBe(before);
  });
});
