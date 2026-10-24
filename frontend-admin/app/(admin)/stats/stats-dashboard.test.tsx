import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RevenueRead, SignupsRead, StatsOverview } from "@/lib/api/schema";

import { StatsDashboard } from "./stats-dashboard";

const OVERVIEW: StatsOverview = {
  computed_at: "2026-10-24T10:45:00Z",
  companies: { trial: 4, active: 7, suspended: 1, total: 12 },
  active_users: 31,
  plans: [
    { code: "starter", name: "Starter", trial: 0, paying: 3, suspended: 1, total: 4 },
    { code: "business", name: "Business", trial: 0, paying: 2, suspended: 0, total: 2 },
    { code: "premium", name: "Premium", trial: 4, paying: 2, suspended: 0, total: 6 },
  ],
  without_subscription: 0,
};

function revenue(query: Record<string, string>): RevenueRead {
  const custom = query.period === "custom";
  return {
    period: query.period as RevenueRead["period"],
    start: custom ? (query.start ?? "") : "2026-10-01",
    end: custom ? (query.end ?? "") : "2026-10-24",
    timezone: "Africa/Dakar",
    total_fcfa: custom ? "4900.00" : "44700.00",
    payment_count: custom ? 1 : 3,
    computed_at: "2026-10-24T10:45:00Z",
  };
}

const DAY = 86_400_000;
const isoDay = (time: number) => new Date(time).toISOString().slice(0, 10);

function signups(granularity: string): SignupsRead {
  const buckets =
    granularity === "month"
      ? Array.from({ length: 12 }, (_, index) => {
          const month = new Date(Date.UTC(2025, 10 + index, 1)).getTime();
          const next = new Date(Date.UTC(2025, 11 + index, 1)).getTime();
          return { start: isoDay(month), end: isoDay(next - DAY), count: 0 };
        })
      : Array.from({ length: 52 }, (_, index) => {
          const monday = Date.UTC(2025, 9, 27) + index * 7 * DAY;
          return { start: isoDay(monday), end: isoDay(monday + 6 * DAY), count: 0 };
        });
  buckets[buckets.length - 1]!.count = 2;
  return {
    granularity: granularity as SignupsRead["granularity"],
    timezone: "Africa/Dakar",
    computed_at: "2026-10-24T10:45:00Z",
    total: 2,
    buckets,
  };
}

const GET = vi.fn(async (path: string, init?: { params?: { query?: Record<string, string> } }) => {
  const query = init?.params?.query ?? {};
  const data =
    path === "/api/v1/platform/stats/overview"
      ? OVERVIEW
      : path === "/api/v1/platform/stats/revenue"
        ? revenue(query)
        : signups(query.granularity ?? "month");
  return { data, response: new Response(null, { status: 200 }) };
});

vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  api: { GET: (...args: unknown[]) => GET(...(args as [string])) },
}));

beforeEach(() => GET.mockClear());

describe("statistiques", () => {
  it("compte les entreprises par statut et par offre, essais à part", async () => {
    render(<StatsDashboard />);
    const tile = (await screen.findByText("Utilisateurs actifs")).parentElement!;
    expect(within(tile).getByText("31")).toBeVisible();
    const premium = screen.getByRole("row", { name: /Premium/ });
    expect(
      within(premium)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(["4", "2", "0", "6"]);
    expect(screen.getByText(/Comptés le 24\/10\/2026 à 10:45/)).toBeVisible();
  });

  it("dit que le revenu vient des paiements enregistrés, et pour quels jours", async () => {
    render(<StatsDashboard />);
    expect(
      screen.getByText(/Basé sur les paiements enregistrés, pas sur les offres en cours/),
    ).toBeVisible();
    expect(await screen.findByText(/^44.700.FCFA$/)).toBeVisible();
    expect(
      screen.getByText(/3 paiements enregistrés du 01\/10\/2026 au 24\/10\/2026/),
    ).toBeVisible();
  });

  it("une période personnalisée attend ses deux dates", async () => {
    render(<StatsDashboard />);
    await screen.findByText(/^44.700.FCFA$/);
    await userEvent.click(screen.getByLabelText("Personnalisée"));
    expect(screen.queryByText(/^44.700.FCFA$/)).toBeNull();
    await userEvent.type(screen.getByLabelText("Du"), "2026-09-01");
    await userEvent.type(screen.getByLabelText("Au"), "2026-09-30");
    await userEvent.click(screen.getByRole("button", { name: "Afficher" }));
    expect(await screen.findByText(/^4.900.FCFA$/)).toBeVisible();
    expect(GET).toHaveBeenLastCalledWith("/api/v1/platform/stats/revenue", {
      params: { query: { period: "custom", start: "2026-09-01", end: "2026-09-30" } },
    });
  });

  it("bascule les nouvelles entreprises du mois à la semaine", async () => {
    render(<StatsDashboard />);
    expect(await screen.findByText(/2 entreprises créées/)).toBeVisible();
    await userEvent.click(screen.getByLabelText("Par semaine"));
    expect(GET).toHaveBeenLastCalledWith("/api/v1/platform/stats/signups", {
      params: { query: { granularity: "week" } },
    });
    expect(await screen.findAllByText(/^Semaine du/)).toHaveLength(52);
  });
});
