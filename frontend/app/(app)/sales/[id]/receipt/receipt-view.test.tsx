import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import type { Schemas } from "@/lib/api/schema";
import { labels } from "@/lib/labels";
import { renderWithClient } from "@/test/render";

import { paidByMethod, ReceiptView } from "./receipt-view";

const t = labels.receipt;
let format = "a4";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/sales/s1/receipt",
  useSearchParams: () => new URLSearchParams(`format=${format}`),
}));
vi.mock("@/hooks/use-me", () => ({
  useMe: () => ({ data: { company: { receipt_format: "ticket" } } }),
  useCompanyLocale: () => ({ currency: "XOF", timeZone: "Africa/Dakar" }),
}));
vi.mock("@/lib/api/client", () => ({
  api: { GET: vi.fn() },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

type Receipt = Schemas["ReceiptRead"];

function line(index: number, extra: Partial<Receipt["lines"][number]> = {}) {
  return {
    product_id: `p${index}`,
    sku: `ART-${index}`,
    name: `Article ${index}`,
    description: null,
    unit: "piece" as const,
    qty: "2.000",
    unit_price: "1500.00",
    discount: "0.00",
    tax_rate: "0.0000",
    tax_amount: "0.00",
    line_total: "3000.00",
    ...extra,
  };
}

function receipt(extra: Partial<Receipt> = {}, company: Partial<Receipt["company"]> = {}): Receipt {
  return {
    sale_id: "s1",
    sale_no: "V-001044",
    status: "confirmed",
    sold_at: "2026-11-04T10:00:00Z",
    confirmed_at: "2026-11-04T10:00:00Z",
    company: {
      name: "Boutique Keur Fatou",
      currency: "XOF",
      address: "Rue 10, Médina, Dakar",
      phone: "77 123 45 67",
      wave_number: null,
      ninea: "0012345",
      rc: "SN-DKR-2020-B-1",
      receipt_footer: "Merci et à bientôt",
      logo_updated_at: null,
      ...company,
    },
    customer: { id: "c1", code: "CLI-0001", name: "Awa Ndiaye", phone: "77 000 00 00" },
    seller_name: "Fatou Diop",
    lines: [
      line(1, { description: "Riz parfumé de la vallée", unit: "kg", qty: "2.500" }),
      line(2, { discount: "200.00", line_total: "2800.00" }),
    ],
    subtotal: "6750.00",
    discount_total: "200.00",
    tax_total: "0.00",
    total: "6550.00",
    paid_total: "5000.00",
    balance: "1550.00",
    payments: [
      payment("1", "cash", "3000.00"),
      payment("2", "wave", "1500.00"),
      payment("3", "cash", "500.00"),
      payment("4", "orange_money", "9999.00", { cancelled: true }),
    ],
    returns: [],
    ...extra,
  } as Receipt;
}

function payment(id: string, method: string, amount: string, extra: object = {}) {
  return {
    id,
    direction: "inflow",
    method,
    amount,
    paid_at: "2026-11-04T10:00:00Z",
    reference: null,
    cancelled: false,
    reversal_of_payment_id: null,
    ...extra,
  };
}

function serve(data: Receipt) {
  vi.mocked(api.GET).mockImplementation((async (path: string) => {
    if (path.endsWith("/logo"))
      return {
        data: new Blob(["png"], { type: "image/png" }),
        error: undefined,
        response: new Response(null),
      };
    if (path.endsWith("/receipt")) return data;
    return { id: "s1", debt: null, items: [] };
  }) as never);
}

beforeEach(() => {
  format = "a4";
  vi.mocked(api.GET).mockReset();
});

describe("Facture A4 refaite (prompt 35, bloc F)", () => {
  it("en-tête : logo, adresse en évidence, identifiants, vendeur ; aucune initiale", async () => {
    serve(receipt({}, { logo_updated_at: "2026-11-04T09:00:00Z" }));
    renderWithClient(<ReceiptView saleId="s1" />);
    const logo = await screen.findByRole(
      "img",
      { name: t.logoAlt("Boutique Keur Fatou") },
      { timeout: 5000 },
    );
    expect(logo.getAttribute("src")).toMatch(/^data:image\/png/);
    expect(screen.getByText("Rue 10, Médina, Dakar")).toHaveClass("font-bold");
    expect(screen.getByText("NINEA 0012345 · RC SN-DKR-2020-B-1")).toBeInTheDocument();
    expect(screen.getByText(t.seller("Fatou Diop"))).toBeInTheDocument();
    expect(screen.queryByText("KF")).toBeNull();
  });

  it("sans logo : les initiales, et rien n'est lu ; sans adresse : aucune ligne vide", async () => {
    serve(receipt({}, { address: null }));
    renderWithClient(<ReceiptView saleId="s1" />);
    expect(await screen.findByText("KF")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /Logo de/ })).toBeNull();
    const calls = vi.mocked(api.GET).mock.calls as unknown as [string][];
    expect(calls.some(([path]) => path.endsWith("/logo"))).toBe(false);
    expect(screen.getByText(/^Le /)).toBeInTheDocument();
  });

  it("lignes : description sous le nom, quantité et unité, remise seulement si elle existe", async () => {
    serve(receipt());
    renderWithClient(<ReceiptView saleId="s1" />);
    const rows = await screen.findAllByTestId("invoice-line");
    expect(within(rows[0]!).getByText("Riz parfumé de la vallée")).toBeInTheDocument();
    expect(within(rows[0]!).getByText(/2,5\s?kg/)).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: t.columns.discount })).toBeInTheDocument();
    for (const cell of within(rows[1]!).getAllByRole("cell").slice(1)) {
      expect(cell).toHaveClass("numeric", "text-right");
    }
  });

  it("sans remise : pas de colonne Remise ni de ligne Remises", async () => {
    serve(
      receipt({
        lines: [line(1)],
        subtotal: "3000.00",
        discount_total: "0.00",
        total: "3000.00",
      }),
    );
    renderWithClient(<ReceiptView saleId="s1" />);
    await screen.findAllByTestId("invoice-line");
    expect(screen.queryByRole("columnheader", { name: t.columns.discount })).toBeNull();
    expect(screen.queryByText(t.discounts)).toBeNull();
  });

  it("totaux : sous-total, remises, payé par moyen (annulé exclu), reste dû ; retours liés", async () => {
    serve(
      receipt({
        returns: [
          { return_no: "R-000007", returned_at: "2026-11-04T12:00:00Z", total_refund: "1500.00" },
        ],
      }),
    );
    renderWithClient(<ReceiptView saleId="s1" />);
    await screen.findAllByTestId("invoice-line");
    expect(screen.getByText(t.subtotal)).toBeInTheDocument();
    expect(screen.getByText(t.discounts)).toBeInTheDocument();
    expect(screen.getByText(t.paidWith("Espèces"))).toBeInTheDocument();
    expect(screen.getByText(t.paidWith("Wave"))).toBeInTheDocument();
    expect(screen.queryByText(/Orange Money/)).toBeNull();
    expect(screen.getByText(t.invoiceRemaining)).toBeInTheDocument();
    expect(screen.getByText(t.returnsTitle)).toBeInTheDocument();
    expect(screen.getByText(/Retour n° 7 du/)).toBeInTheDocument();
    expect(screen.getByText("Merci et à bientôt")).toBeInTheDocument();
  });

  it("facture longue : l'en-tête du tableau se répète, une ligne ne se coupe pas, pages numérotées", async () => {
    serve(receipt({ lines: Array.from({ length: 40 }, (_, index) => line(index)) }));
    const { container } = renderWithClient(<ReceiptView saleId="s1" />);
    const rows = await screen.findAllByTestId("invoice-line");
    expect(rows).toHaveLength(40);
    expect(rows.every((row) => row.classList.contains("break-inside-avoid"))).toBe(true);
    expect(container.querySelector("thead")).toHaveClass("table-header-group");
    const style = container.querySelector("style")?.textContent ?? "";
    expect(style).toContain("counter(page)");
    expect(style).toContain("counter(pages)");
    expect(style).toContain("size: A4");
  });

  it("le prix de la fiche n'apparaît jamais : seul le prix appliqué est imprimé", async () => {
    serve(receipt({ lines: [line(1, { unit_price: "1200.00", line_total: "2400.00" })] }));
    renderWithClient(<ReceiptView saleId="s1" />);
    await screen.findAllByTestId("invoice-line");
    expect(screen.queryByText(/prix changé/i)).toBeNull();
  });
});

describe("Petit ticket refait (prompt 35, bloc F)", () => {
  it("logo en noir et blanc, adresse, lignes courtes sans description, mêmes totaux", async () => {
    format = "ticket";
    serve(receipt({}, { logo_updated_at: "2026-11-04T09:00:00Z" }));
    renderWithClient(<ReceiptView saleId="s1" />);
    const logo = await screen.findByRole(
      "img",
      { name: t.logoAlt("Boutique Keur Fatou") },
      { timeout: 5000 },
    );
    expect(logo).toHaveClass("grayscale");
    expect(screen.getByText("Rue 10, Médina, Dakar")).toBeInTheDocument();
    const lines = screen.getAllByTestId("ticket-line");
    expect(lines).toHaveLength(2);
    expect(within(lines[1]!).getByText(/^\s*2 x /)).toBeInTheDocument();
    expect(screen.queryByText("Riz parfumé de la vallée")).toBeNull();
    // Lignes courtes de la maquette 05 : la quantité seule ; l'unité est sur la facture.
    expect(screen.getByText(/^\s*2,5 x /)).toBeInTheDocument();
    expect(screen.getByText(t.lineDiscount)).toBeInTheDocument();
    expect(screen.getByText(t.subtotal)).toBeInTheDocument();
    expect(screen.getByText(t.remaining)).toBeInTheDocument();
    expect(screen.getByText("Merci et à bientôt")).toBeInTheDocument();
  });

  it("sans logo : aucun appel, aucune image", async () => {
    format = "ticket";
    serve(receipt());
    renderWithClient(<ReceiptView saleId="s1" />);
    await screen.findAllByTestId("ticket-line");
    expect(screen.queryByRole("img", { name: /Logo de/ })).toBeNull();
  });
});

describe("paidByMethod", () => {
  it("additionne en décimal, sans arrondi flottant", () => {
    const rows = paidByMethod(
      receipt({
        payments: [payment("1", "cash", "0.10"), payment("2", "cash", "0.20")] as never,
      }),
    );
    expect(rows).toEqual([{ method: "Espèces", amount: "0.30" }]);
  });
});
