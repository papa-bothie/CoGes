import { screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithClient } from "@/test/render";

import { PeopleListView } from "./people-list-view";

const state = vi.hoisted(() => ({ money: true }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/customers",
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/hooks/use-me", () => ({
  useCompanyLocale: () => ({ currency: "XOF", timeZone: "Africa/Dakar" }),
  useMe: () => ({ data: undefined }),
}));
vi.mock("@/hooks/use-permission", () => ({
  usePermission: (rule: string) => rule !== "debts:read" || state.money,
  Can: ({ children }: { children: ReactNode }) => children,
}));
vi.mock("@/lib/api/client", () => ({
  api: {
    GET: vi.fn(async () => ({
      items: [
        {
          id: "moussa",
          name: "Moussa Fall",
          phone: "76 220 15 90",
          owed: state.money ? "25000.00" : null,
          owed_since: state.money ? new Date(Date.now() - 12 * 86_400_000).toISOString() : null,
          due_date: null,
          last_seen_at: new Date().toISOString(),
        },
        {
          id: "zeynab",
          name: "Zeynab Ka",
          phone: null,
          owed: state.money ? "0.00" : null,
          owed_since: null,
          due_date: null,
          last_seen_at: null,
        },
      ],
      page: 1,
      page_size: 50,
      total: 2,
      owing_count: state.money ? 1 : null,
      owed_total: state.money ? "25000.00" : null,
      customer_count: 2,
      supplier_count: 5,
    })),
  },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

beforeEach(() => {
  state.money = true;
});

describe("Clients et fournisseurs", { timeout: 15_000 }, () => {
  it("résume ce qui est dû et dit qui doit depuis quand", async () => {
    renderWithClient(<PeopleListView kind="customer" />);
    expect(await screen.findByText("1 client vous doit 25 000 F au total")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Clients (2)" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Fournisseurs (5)" })).toHaveAttribute(
      "href",
      "/suppliers",
    );
    const moussa = screen.getByRole("link", { name: /Moussa Fall/ });
    expect(moussa).toHaveTextContent(/Doit 25\s000\sF/);
    expect(moussa).toHaveTextContent("Depuis 12 jours");
    expect(screen.getByRole("link", { name: /Zeynab Ka/ })).toHaveTextContent("Aucun achat");
    expect(screen.getByRole("button", { name: "Qui me doivent" })).toBeInTheDocument();
  });

  it("ne montre aucun montant à un vendeur", async () => {
    state.money = false;
    renderWithClient(<PeopleListView kind="customer" />);
    expect(await screen.findByText("2 clients")).toBeInTheDocument();
    expect(screen.queryByText(/Doit/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Qui me doivent" })).not.toBeInTheDocument();
  });
});
