import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { labels } from "@/lib/labels";
import { BUSINESS_EXTRAS, FEATURE_LABELS, PRO } from "@/lib/offres";
import { renderWithClient } from "@/test/render";

import { SubscriptionView } from "./subscription-view";

const t = labels.settingsScreens.subscription;

let current: Record<string, unknown> = {};

vi.mock("@/hooks/use-me", () => ({
  useCompanyLocale: () => ({ timeZone: "Africa/Dakar", currency: "XOF" }),
}));
vi.mock("@/lib/api/client", () => ({
  api: { GET: vi.fn(async () => current) },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

function subscription(overrides: Record<string, unknown> = {}) {
  return {
    code: "starter",
    name: "Pro",
    status: "trial",
    is_license: false,
    features: [...PRO.features],
    trial_ends_at: "2026-12-25T10:00:00Z",
    current_period_end: null,
    max_users: 3,
    active_users: 2,
    extra_features: [],
    ...overrides,
  };
}

function hrefs(): string[] {
  return screen.getAllByRole("link").map((link) => decodeURIComponent(link.getAttribute("href")!));
}

describe("Mon abonnement pendant la grâce (ADR 0133)", () => {
  it("un essai terminé dit le jour de la pause", async () => {
    current = subscription({
      status: "past_due",
      renewal: {
        kind: "trial",
        stage: "due",
        ends_at: "2026-12-25T10:00:00Z",
        pause_on: "2026-12-28",
        days_left: 3,
      },
    });
    renderWithClient(<SubscriptionView />);
    expect(await screen.findByTestId("subscription-status")).toHaveTextContent(
      "Essai gratuit terminé le 25 décembre 2026. Mise en pause prévue le lundi 28 décembre.",
    );
  });
});

describe("Mon abonnement (prompt 41, B4)", () => {
  it("essai : l'offre, la fin d'essai, les comptes, et les deux montants", async () => {
    current = subscription();
    renderWithClient(<SubscriptionView />);
    expect(await screen.findByText("CoGes Pro")).toBeInTheDocument();
    expect(screen.getByTestId("subscription-status")).toHaveTextContent(
      "Essai gratuit jusqu'au 25 décembre 2026",
    );
    expect(screen.getByText("2 comptes sur 3")).toBeInTheDocument();
    expect(screen.getByText("4 900 F")).toBeInTheDocument();
    expect(screen.getByText("52 920 F")).toBeInTheDocument();
    expect(screen.getByText("par an (-10 %)")).toBeInTheDocument();
    expect(hrefs()).toEqual(
      expect.arrayContaining([
        expect.stringContaining("Je veux payer CoGes Pro pour 1 mois."),
        expect.stringContaining("Je veux payer CoGes Pro pour 1 an."),
        expect.stringContaining("Je veux passer à CoGes Business."),
      ]),
    );
    // Ce qu'ajoute Business, import compris.
    const extras = screen
      .getByRole("heading", { name: "Ce qu'ajoute Business" })
      .closest("section")!;
    for (const code of BUSINESS_EXTRAS) {
      expect(within(extras).getByText(FEATURE_LABELS[code])).toBeInTheDocument();
    }
    expect(screen.queryByText(t.acquired)).toBeNull();
  });

  it("payé : « Payé jusqu'au … »", async () => {
    current = subscription({ status: "active", current_period_end: "2027-01-15T00:00:00Z" });
    renderWithClient(<SubscriptionView />);
    expect(await screen.findByTestId("subscription-status")).toHaveTextContent(
      "Payé jusqu'au 15 janvier 2027",
    );
  });

  it("suspendu : « Suspendu », et le paiement reste proposé", async () => {
    current = subscription({ status: "suspended" });
    renderWithClient(<SubscriptionView />);
    expect(await screen.findByTestId("subscription-status")).toHaveTextContent("Suspendu");
    expect(screen.getByText(t.howToPay)).toBeInTheDocument();
  });

  it("sur site : la licence, sans paiement ni échéance", async () => {
    current = subscription({ status: "active", is_license: true, trial_ends_at: null });
    renderWithClient(<SubscriptionView />);
    expect(await screen.findByTestId("subscription-status")).toHaveTextContent(
      "Licence sur site, offre Pro",
    );
    expect(screen.queryByText(t.howToPay)).toBeNull();
    expect(screen.queryByText(/jusqu'au/)).toBeNull();
  });

  it("droits acquis : l'import et le plafond de la boutique sont dits", async () => {
    current = subscription({
      features: [...PRO.features, "imports"],
      extra_features: ["imports"],
      max_users: 5,
      active_users: 5,
    });
    renderWithClient(<SubscriptionView />);
    expect(await screen.findByText(t.acquiredImports)).toBeInTheDocument();
    expect(screen.getByText("Jusqu'à 5 comptes pour votre boutique")).toBeInTheDocument();
    expect(screen.getByText("5 comptes sur 5")).toBeInTheDocument();
    const extras = screen
      .getByRole("heading", { name: "Ce qu'ajoute Business" })
      .closest("section")!;
    expect(within(extras).queryByText(FEATURE_LABELS.imports)).toBeNull();
  });

  it("Business : rien à ajouter, les montants de Business", async () => {
    current = subscription({
      code: "business",
      name: "Business",
      status: "active",
      current_period_end: "2027-01-15T00:00:00Z",
      max_users: 7,
      features: [...PRO.features, ...BUSINESS_EXTRAS],
    });
    renderWithClient(<SubscriptionView />);
    expect(await screen.findByText("CoGes Business")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Ce qu'ajoute Business" })).toBeNull();
    expect(screen.getByText("9 900 F")).toBeInTheDocument();
    expect(screen.getByText("106 920 F")).toBeInTheDocument();
  });
});
