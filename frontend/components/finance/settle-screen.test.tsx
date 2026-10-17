import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Schemas } from "@/lib/api/schema";
import { renderWithClient } from "@/test/render";

import { SettleScreen } from "./settle-screen";

const debt = (id: string, principal: string, balance: string, created: string, sale: string) =>
  ({
    id,
    party_type: "customer",
    customer_id: "moussa",
    supplier_id: null,
    party_name: "Moussa Fall",
    sale_id: sale,
    principal,
    balance,
    amount_paid: "0.00",
    status: "open",
    due_date: null,
    created_at: created,
  }) as unknown as Schemas["DebtDetail"];

// Volontairement dans le désordre : l'écran règle d'abord la plus ancienne.
const DEBTS = [
  debt("d2", "12500.00", "10000.00", "2026-10-01T09:00:00Z", "s2"),
  debt("d1", "30000.00", "15000.00", "2026-09-24T10:15:00Z", "s1"),
];
const PEOPLE = {
  items: [
    {
      id: "awa",
      name: "Awa Diop",
      phone: null,
      owed: "4000.00",
      owed_since: "2026-10-05T10:00:00Z",
      due_date: null,
      last_seen_at: null,
    },
    {
      id: "moussa",
      name: "Moussa Fall",
      phone: "76 220 15 90",
      owed: "25000.00",
      owed_since: "2026-09-24T10:15:00Z",
      due_date: null,
      last_seen_at: null,
    },
  ],
  page: 1,
  page_size: 100,
  total: 2,
  owing_count: 2,
  owed_total: "29000.00",
  customer_count: 15,
  supplier_count: 5,
};
const SALES = {
  items: [
    { sale_id: "s1", item_names: ["Riz brisé 25 kg", "Huile Dinor 1 L", "Sucre"] },
    { sale_id: "s2", item_names: ["Lait en poudre", "Café Touba"] },
  ],
};

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/hooks/use-me", () => ({
  useCompanyLocale: () => ({ currency: "XOF", timeZone: "Africa/Dakar" }),
}));
vi.mock("@/lib/api/client", () => ({
  api: {
    GET: vi.fn(async (path: string) =>
      path === "/api/v1/analytics/customers"
        ? PEOPLE
        : path === "/api/v1/debts"
          ? { items: DEBTS, page: 1, page_size: 100, total: 2 }
          : SALES,
    ),
    POST: vi.fn(async () => ({ id: "p1" })),
  },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

beforeEach(() => vi.mocked(api.POST).mockClear());

describe("Encaisser une dette (écran 18)", { timeout: 15_000 }, () => {
  it("choisit la plus vieille dette, répartit et annonce ce qui reste", async () => {
    renderWithClient(<SettleScreen kind="customer" />);
    // Moussa Fall doit depuis le plus longtemps : il est choisi d'office.
    expect(await screen.findByRole("heading", { name: "Moussa Fall" })).toBeInTheDocument();
    expect(await screen.findByText("Riz, huile, sucre")).toBeInTheDocument();
    expect(screen.getByText("Lait, café")).toBeInTheDocument();

    const submit = screen.getByRole("button", { name: /^Encaisser/ });
    expect(submit).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /^Tout : 25\s000\sF$/ }));
    expect(screen.getByText("Il ne devra plus rien")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Effacer le dernier chiffre"));
    await userEvent.click(screen.getByLabelText("Effacer le dernier chiffre"));
    await userEvent.click(screen.getByLabelText("Effacer le dernier chiffre"));
    await userEvent.click(screen.getByRole("button", { name: "000" }));
    await userEvent.click(screen.getByRole("button", { name: "Wave" }));
    expect(screen.getByLabelText("Combien il paie ?")).toHaveValue("25000");

    await userEvent.clear(screen.getByLabelText("Combien il paie ?"));
    await userEvent.type(screen.getByLabelText("Combien il paie ?"), "17500");
    expect(screen.getByText("Il restera 7 500 F à payer")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^Encaisser 17\s500\sF$/ }));
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/payments",
      expect.objectContaining({
        body: {
          direction: "inflow",
          method: "wave",
          amount: "17500",
          allocations: [
            { debt_id: "d1", amount: "15000.00" },
            { debt_id: "d2", amount: "2500.00" },
          ],
        },
      }),
    );
    expect(await screen.findByText("17 500 F reçus. Il reste 7 500 F.")).toBeInTheDocument();
  });

  it("après un échec, garde la saisie et réessaie avec la même clé (ADR 0085)", async () => {
    vi.mocked(api.POST)
      .mockRejectedValueOnce(new ApiError(503, "server_error", "Un souci de notre côté."))
      .mockResolvedValueOnce({ id: "p1" } as never);
    renderWithClient(<SettleScreen kind="customer" />);
    await screen.findByRole("heading", { name: "Moussa Fall" });
    await userEvent.type(await screen.findByLabelText("Combien il paie ?"), "5000");
    const submit = screen.getByRole("button", { name: /^Encaisser 5\s000\sF$/ });

    await userEvent.click(submit);
    expect(await screen.findByText("Un souci de notre côté.")).toBeInTheDocument();
    // Rien n'est rejoué tout seul : un seul envoi, la saisie est toujours là.
    expect(api.POST).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Combien il paie ?")).toHaveValue("5000");

    await userEvent.click(screen.getByRole("button", { name: /^Encaisser 5\s000\sF$/ }));
    expect(api.POST).toHaveBeenCalledTimes(2);
    const keys = vi
      .mocked(api.POST)
      .mock.calls.map(
        (call) => (call[1] as { headers: Record<string, string> }).headers["Idempotency-Key"],
      );
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBe(keys[0]);
  });

  it("refuse plus que ce qui est dû", async () => {
    renderWithClient(<SettleScreen kind="customer" />);
    await screen.findByRole("heading", { name: "Moussa Fall" });
    await userEvent.type(await screen.findByLabelText("Combien il paie ?"), "30000");
    expect(screen.getByText("C’est plus que ce qu’il doit (25 000 F)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Encaisser/ })).toBeDisabled();
  });
});
