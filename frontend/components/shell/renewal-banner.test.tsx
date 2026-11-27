import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { labels } from "@/lib/labels";

import { RenewalBanner, hiddenKey } from "./renewal-banner";

type Renewal = {
  kind: "trial" | "paid";
  stage: "eve" | "due" | "last";
  ends_at: string;
  pause_on: string;
  days_left: number;
};

const state = vi.hoisted(() => ({
  renewal: null as null | Renewal,
  permissions: ["company:update"] as string[],
  viaSupport: false,
}));

vi.mock("@/hooks/use-me", () => ({
  useMe: () => ({
    data: {
      via_support: state.viaSupport,
      permissions: state.permissions,
      company: { id: "c1", timezone: "Africa/Dakar" },
      plan: { name: "Pro", renewal: state.renewal },
    },
  }),
}));

const NOW = () => Date.parse("2026-12-10T09:00:00Z");
const step = (stage: Renewal["stage"], kind: Renewal["kind"] = "trial", days = 3): Renewal => ({
  kind,
  stage,
  ends_at: "2026-12-10T12:00:00Z",
  pause_on: "2026-12-13",
  days_left: days,
});

describe("bandeau de relance (ADR 0133)", () => {
  beforeEach(() => {
    window.localStorage.clear();
    state.permissions = ["company:update"];
    state.viaSupport = false;
  });

  it("ne dit rien hors de la fenêtre des relances", () => {
    state.renewal = null;
    const { container } = render(<RenewalBanner now={NOW} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("la veille, le gérant lit le message et le bouton vers « Mon abonnement »", () => {
    state.renewal = step("eve", "trial", 4);
    render(<RenewalBanner now={NOW} />);
    expect(screen.getByRole("status")).toHaveTextContent(labels.renewal.eve("trial", "Pro"));
    expect(screen.getByRole("link", { name: labels.renewal.choose })).toHaveAttribute(
      "href",
      "/settings/subscription",
    );
    expect(screen.getByRole("status")).toHaveTextContent("le dimanche 13 décembre");
  });

  it("le jour J dit combien de jours restent, pour un abonnement aussi", () => {
    state.renewal = step("due", "paid", 3);
    render(<RenewalBanner now={NOW} />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Votre abonnement se termine aujourd’hui. Pas d’inquiétude : votre boutique reste ouverte encore 3 jours",
    );
  });

  it("calme avant le dernier rappel, orange au dernier rappel", () => {
    state.renewal = step("due");
    const { unmount } = render(<RenewalBanner now={NOW} />);
    expect(screen.getByRole("status").className).toContain("bg-conseils-teinte");
    unmount();
    state.renewal = step("last", "trial", 1);
    render(<RenewalBanner now={NOW} />);
    expect(screen.getByRole("status").className).toContain("bg-stock-teinte");
    expect(screen.getByRole("status")).toHaveTextContent(labels.renewal.last);
  });

  it("les autres rôles ne voient que le dernier rappel, sans bouton d'offre", () => {
    state.permissions = ["sales:create"];
    state.renewal = step("due");
    const { container, unmount } = render(<RenewalBanner now={NOW} />);
    expect(container).toBeEmptyDOMElement();
    unmount();
    state.renewal = step("last", "trial", 1);
    render(<RenewalBanner now={NOW} />);
    expect(screen.getByRole("status")).toHaveTextContent(labels.renewal.lastOthers);
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("se replie pour la journée, et revient le lendemain", () => {
    state.renewal = step("due");
    const { unmount } = render(<RenewalBanner now={NOW} />);
    fireEvent.click(screen.getByRole("button", { name: labels.renewal.hide }));
    expect(screen.queryByRole("status")).toBeNull();
    expect(window.localStorage.getItem(hiddenKey("c1", "due", "2026-12-10"))).toBe("1");
    unmount();
    render(<RenewalBanner now={NOW} />);
    expect(screen.queryByRole("status")).toBeNull();

    const tomorrow = () => Date.parse("2026-12-11T09:00:00Z");
    render(<RenewalBanner now={tomorrow} />);
    expect(screen.getByRole("status")).toBeVisible();
  });

  it("jamais sous l'accès support", () => {
    state.viaSupport = true;
    state.renewal = step("last", "trial", 1);
    const { container } = render(<RenewalBanner now={NOW} />);
    expect(container).toBeEmptyDOMElement();
  });
});
