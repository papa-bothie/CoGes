import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import type { Schemas } from "@/lib/api/schema";
import { renderWithClient } from "@/test/render";

import { SettleDialog } from "./settle-dialog";

const debt = (id: string, principal: string, balance: string, created: string) =>
  ({
    id,
    party_type: "customer",
    customer_id: "moussa",
    supplier_id: null,
    party_name: "Moussa Fall",
    principal,
    balance,
    amount_paid: "0.00",
    status: "open",
    due_date: null,
    created_at: created,
  }) as unknown as Schemas["DebtDetail"];

const DEBTS = [
  debt("d1", "30000.00", "15000.00", "2026-09-24T10:15:00Z"),
  debt("d2", "12500.00", "10000.00", "2026-10-01T09:00:00Z"),
];

vi.mock("@/hooks/use-me", () => ({
  useCompanyLocale: () => ({ currency: "XOF", timeZone: "Africa/Dakar" }),
}));
vi.mock("@/lib/api/client", () => ({
  api: {
    GET: vi.fn(async () => ({ items: DEBTS, page: 1, page_size: 100, total: 2 })),
    POST: vi.fn(async () => ({ id: "p1" })),
    PATCH: vi.fn(),
  },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

beforeEach(() => vi.mocked(api.POST).mockClear());

describe("Encaisser une dette", { timeout: 15_000 }, () => {
  it("se tape librement, dit ce qui restera et répartit sur les plus anciennes", async () => {
    renderWithClient(<SettleDialog debt={DEBTS[0]!} onClose={() => {}} />);
    expect(await screen.findByText(`25 000 F`)).toBeInTheDocument();
    expect(screen.queryByText(/Référence/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Note/)).not.toBeInTheDocument();

    const encaisser = screen.getByRole("button", { name: "Encaisser" });
    expect(encaisser).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "2" }));
    await userEvent.click(screen.getByRole("button", { name: "1" }));
    await userEvent.click(screen.getByRole("button", { name: "000" }));
    expect(screen.getByLabelText("Combien il paie ?")).toHaveValue("21000");
    expect(screen.getByText(`Il restera 4 000 F à payer`)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Wave" }));
    await userEvent.click(encaisser);
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/payments",
      expect.objectContaining({
        body: {
          direction: "inflow",
          method: "wave",
          amount: "21000",
          allocations: [
            { debt_id: "d1", amount: "15000.00" },
            { debt_id: "d2", amount: "6000.00" },
          ],
        },
      }),
    );
  });

  it("refuse plus que ce qui est dû", async () => {
    renderWithClient(<SettleDialog debt={DEBTS[0]!} onClose={() => {}} />);
    await screen.findByText(`25 000 F`);
    await userEvent.type(screen.getByLabelText("Combien il paie ?"), "30000");
    expect(screen.getByText(`C’est plus que ce qu’il doit (25 000 F)`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Encaisser" })).toBeDisabled();
  });

  it("propose « Tout » et « La moitié »", async () => {
    renderWithClient(<SettleDialog debt={DEBTS[0]!} onClose={() => {}} />);
    await screen.findByText(`25 000 F`);
    await userEvent.click(screen.getByRole("button", { name: /^Tout : 25\s000\sF$/ }));
    expect(screen.getByText("Il ne devra plus rien")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^La moitié : 12\s500\sF$/ }));
    expect(screen.getByLabelText("Combien il paie ?")).toHaveValue("12500");
  });
});
