import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";

import { RecentSales } from "./recent-sales";

vi.mock("@/lib/api/client", () => ({
  api: { GET: vi.fn() },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

const get = vi.mocked(api.GET);

function sale(overrides: Record<string, unknown>) {
  return {
    id: "s1",
    sale_no: "V-000042",
    customer_id: null,
    customer_name: null,
    status: "confirmed",
    sold_at: "2026-10-06T10:15:00Z",
    subtotal: "3000.00",
    discount_total: "0.00",
    tax_total: "0.00",
    total: "3000.00",
    paid_total: "3000.00",
    balance: "0.00",
    debt_status: null,
    has_returns: false,
    returned_total: "0.00",
    cancel_reason: null,
    confirmed_at: "2026-10-06T10:15:00Z",
    cancelled_at: null,
    item_count: 2,
    ...overrides,
  };
}

function renderBlock() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RecentSales currency="XOF" timeZone="Africa/Dakar" />
    </QueryClientProvider>,
  );
}

describe("RecentSales", () => {
  beforeEach(() => get.mockReset());

  it("demande les 8 dernières ventes, sans brouillon", async () => {
    get.mockResolvedValue({ items: [], page: 1, page_size: 8, total: 0 } as never);
    renderBlock();
    await screen.findByText("Aucune vente pour l'instant");
    expect(get).toHaveBeenCalledWith("/api/v1/sales", {
      params: { query: { include_drafts: false, page: 1, page_size: 8 } },
    });
  });

  it("une erreur de chargement n'empêche pas de vendre", async () => {
    // L'échec est posé dans le cache (une lecture déjà refusée) : aucun rejet de promesse à
    // intercepter, et le bloc ne relance pas tout seul la lecture.
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, retryOnMount: false, staleTime: Infinity } },
    });
    client
      .getQueryCache()
      .build(client, { queryKey: ["sales", "list", { recent: true }] })
      .setState({
        status: "error",
        error: new Error("réseau"),
        fetchStatus: "idle",
        errorUpdatedAt: Date.now(),
      });
    render(
      <QueryClientProvider client={client}>
        <RecentSales currency="XOF" timeZone="Africa/Dakar" />
      </QueryClientProvider>,
    );
    expect(
      await screen.findByText(
        "Les dernières ventes ne se chargent pas. Vous pouvez vendre quand même.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Réessayer" })).toBeInTheDocument();
    expect(get).not.toHaveBeenCalled();
  });

  it("une vente annulée se lit sans la couleur : mot et icône", async () => {
    get.mockResolvedValue({
      items: [
        sale({ id: "s2", sale_no: "V-000043", customer_name: "Awa Diop", status: "cancelled" }),
        sale({ id: "s1" }),
      ],
      page: 1,
      page_size: 8,
      total: 2,
    } as never);
    renderBlock();
    const rows = await screen.findAllByRole("listitem");
    expect(rows).toHaveLength(2);
    const cancelled = within(rows[0]!);
    expect(cancelled.getByText("Awa Diop")).toBeInTheDocument();
    expect(cancelled.getByText("Annulée")).toBeInTheDocument();
    expect(rows[0]!.querySelector("svg[data-state='cancelled']")).not.toBeNull();
    expect(cancelled.getByRole("link")).toHaveAttribute("href", "/sales/s2");
    expect(within(rows[1]!).getByText("Client de passage")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Voir toutes les ventes" })).toHaveAttribute(
      "href",
      "/sales",
    );
  });

  it("se replie et se déplie", async () => {
    get.mockResolvedValue({ items: [sale({})], page: 1, page_size: 8, total: 1 } as never);
    renderBlock();
    await screen.findAllByRole("listitem");
    const toggle = screen.getByRole("button", { name: "Dernières ventes" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });
});
