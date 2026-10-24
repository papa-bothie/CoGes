import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SupportBanner } from "./support-banner";

const state = vi.hoisted(() => ({
  session: null as null | { started_at: string; expires_at: string },
  viaSupport: false,
}));

vi.mock("@/hooks/use-me", () => ({
  useMe: () => ({ data: { via_support: state.viaSupport } }),
  useCompanyLocale: () => ({ timeZone: "Africa/Dakar", currency: "XOF" }),
}));
vi.mock("@/lib/api/client", () => ({
  api: { GET: vi.fn(async () => ({ session: state.session })) },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

const OPEN = { started_at: "2026-10-24T10:15:00Z", expires_at: "2026-10-24T12:15:00Z" };
const DURING = () => Date.parse("2026-10-24T11:00:00Z");

function renderBanner(now = DURING) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SupportBanner now={now} />
    </QueryClientProvider>,
  );
}

describe("bandeau d'accès support (ADR 0092)", () => {
  it("dit depuis quand et jusqu'à quand, dans le fuseau de la boutique", async () => {
    state.session = OPEN;
    state.viaSupport = false;
    renderBanner();
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Accès support actif depuis 10 h 15, par l’équipe CoGes, jusqu’à 12 h 15",
    );
    expect(screen.queryByText(/lecture seule/)).toBeNull();
  });

  it("rappelle la lecture seule à l'équipe", async () => {
    state.session = OPEN;
    state.viaSupport = true;
    renderBanner();
    expect(await screen.findByText(/en lecture seule/)).toBeVisible();
  });

  it("se tait sans accès ouvert, ou passé son heure", async () => {
    state.session = null;
    renderBanner();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("status")).toBeNull();

    state.session = OPEN;
    renderBanner(() => Date.parse("2026-10-24T12:16:00Z"));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("status")).toBeNull();
  });
});
