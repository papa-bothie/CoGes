import { readFileSync } from "node:fs";
import { join } from "node:path";

import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import type { Schemas } from "@/lib/api/schema";
import { labels } from "@/lib/labels";
import { renderWithClient } from "@/test/render";

import { contrast, luminance } from "@/test/contrast";
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

describe("Facture A4 claire (modèle docs/design/references/modele-facture.jpg ; lot A, ADR 0130)", () => {
  it("papier : jetons clairs même en sombre, couleurs gardées à l'impression", async () => {
    serve(receipt());
    renderWithClient(<ReceiptView saleId="s1" />);
    const invoice = await screen.findByRole("article", { name: t.title("1044") });
    expect(invoice).toHaveClass("papier", "[print-color-adjust:exact]");
  });

  it("en-tête : logo à gauche, téléphone et adresse à pastille claire, filet vert", async () => {
    serve(receipt({}, { logo_updated_at: "2026-11-04T09:00:00Z" }));
    renderWithClient(<ReceiptView saleId="s1" />);
    const logo = await screen.findByRole(
      "img",
      { name: t.logoAlt("Boutique Keur Fatou") },
      { timeout: 5000 },
    );
    expect(logo.getAttribute("src")).toMatch(/^data:image\/png/);
    const header = screen.getByRole("banner");
    expect(header).toHaveClass("border-facture-filet");
    const contacts = within(header).getAllByRole("listitem");
    expect(contacts.map((item) => item.textContent)).toEqual([
      "77 123 45 67",
      "Rue 10, Médina, Dakar",
    ]);
    for (const item of contacts) {
      expect(item.querySelector("[data-pastille]")).toHaveClass(
        "rounded-full",
        "border-facture-filet",
        "bg-facture-accent-clair",
        "text-facture-accent",
      );
    }
    expect(screen.queryByText("KF")).toBeNull();
  });

  it("titre « FACTURE » en vert, numéro et date dessous, à droite", async () => {
    serve(receipt());
    renderWithClient(<ReceiptView saleId="s1" />);
    const title = await screen.findByText(t.invoice, { exact: true });
    expect(title).toHaveClass("text-facture-accent");
    const block = title.parentElement!;
    expect(block).toHaveClass("text-right");
    expect(within(block).getByText(t.invoiceNoLabel)).toBeInTheDocument();
    expect(within(block).getByText("F-1044")).toBeInTheDocument();
    expect(within(block).getByText("4 novembre 2026")).toBeInTheDocument();
    expect(within(block).getByText(t.seller("Fatou Diop"))).toBeInTheDocument();
  });

  it("« De » : nom, adresse, téléphone, NINEA et RC de la boutique", async () => {
    serve(receipt());
    renderWithClient(<ReceiptView saleId="s1" />);
    const from = await screen.findByRole("region", { name: t.from });
    expect(within(from).getByText("Boutique Keur Fatou")).toBeInTheDocument();
    expect(within(from).getByText("Rue 10, Médina, Dakar")).toBeInTheDocument();
    expect(within(from).getByText(t.phone("77 123 45 67"))).toBeInTheDocument();
    expect(within(from).getByText("NINEA 0012345 · RC SN-DKR-2020-B-1")).toBeInTheDocument();
  });

  it("« Facturé à » : le client, ou « Client de passage » sans client", async () => {
    serve(receipt());
    const { unmount } = renderWithClient(<ReceiptView saleId="s1" />);
    const billed = await screen.findByRole("region", { name: t.billedTo });
    expect(billed).toHaveClass("bg-facture-accent-clair");
    expect(within(billed).getByText("Awa Ndiaye")).toBeInTheDocument();
    expect(within(billed).getByText(t.phone("77 000 00 00"))).toBeInTheDocument();
    unmount();
    serve(receipt({ customer: null }));
    renderWithClient(<ReceiptView saleId="s1" />);
    const passing = await screen.findByRole("region", { name: t.billedTo });
    expect(within(passing).getByText(t.walkIn)).toBeInTheDocument();
  });

  it("sans logo : les initiales vertes dans un rond clair, rien n'est lu ; sans adresse : rien de vide", async () => {
    serve(receipt({}, { address: null }));
    renderWithClient(<ReceiptView saleId="s1" />);
    expect(await screen.findByText("KF")).toHaveClass(
      "bg-facture-accent-clair",
      "text-facture-accent",
    );
    expect(screen.queryByRole("img", { name: /Logo de/ })).toBeNull();
    const calls = vi.mocked(api.GET).mock.calls as unknown as [string][];
    expect(calls.some(([path]) => path.endsWith("/logo"))).toBe(false);
    expect(within(screen.getByRole("banner")).getAllByRole("listitem")).toHaveLength(1);
  });

  it("tableau : en-tête clair entre deux filets, N°, description et remise en petit, lignes alternées, montants à droite", async () => {
    serve(receipt());
    renderWithClient(<ReceiptView saleId="s1" />);
    const rows = await screen.findAllByTestId("invoice-line");
    const headers = screen.getAllByRole("columnheader");
    expect(headers.map((cell) => cell.textContent)).toEqual([
      t.columns.no,
      t.columns.article,
      t.columns.price,
      t.columns.qty,
      t.columns.total,
    ]);
    expect(headers[0]!.closest("tr")).toHaveClass(
      "bg-facture-accent-clair",
      "border-facture-filet",
      "text-recu-encre",
    );
    expect(within(rows[0]!).getByText("01")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("Riz parfumé de la vallée")).toBeInTheDocument();
    expect(within(rows[0]!).getByText(/2,5\s?kg/)).toBeInTheDocument();
    expect(within(rows[1]!).getByText(/Remise : -200\sF/)).toBeInTheDocument();
    expect(rows[0]).toHaveClass("even:bg-recu-entete");
    for (const cell of within(rows[1]!).getAllByRole("cell").slice(2)) {
      expect(cell).toHaveClass("numeric", "text-right");
    }
  });

  it("totaux : sous-total, remises, « Total » clair entre deux filets, puis payé et reste dû", async () => {
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
    expect(screen.queryByText(t.vat)).toBeNull();
    // « Total » nomme aussi la dernière colonne du tableau : on prend celui des totaux.
    const total = screen
      .getAllByText(t.invoiceTotal)
      .find((element) => element.tagName === "SPAN")!.parentElement!;
    expect(total).toHaveClass("bg-facture-accent-clair", "border-facture-filet", "text-recu-encre");
    expect(screen.getByText(t.alreadyPaid)).toBeInTheDocument();
    expect(screen.getByText(t.invoiceRemaining)).toBeInTheDocument();
    expect(screen.getByText(/Retour n° 7 du/)).toBeInTheDocument();
  });

  it("bas de page : merci, moyens de paiement utilisés (annulé exclu), pied de reçu, signature", async () => {
    serve(receipt());
    renderWithClient(<ReceiptView saleId="s1" />);
    await screen.findAllByTestId("invoice-line");
    const footer = screen.getByRole("contentinfo");
    expect(within(footer).getByText(t.thanks)).toBeInTheDocument();
    const methods = within(footer).getByRole("list", { name: t.paymentMethods });
    expect(within(methods).getByText(/Espèces/)).toBeInTheDocument();
    expect(within(methods).getByText(/Wave/)).toBeInTheDocument();
    expect(within(footer).queryByText(/Orange Money/)).toBeNull();
    expect(within(footer).getByText("Merci et à bientôt")).toBeInTheDocument();
    expect(within(footer).getByText(t.signature).parentElement).toHaveClass("border-2");
  });

  it("vente annulée : ni payé, ni reste dû, ni somme arrêtée ; le tampon reste", async () => {
    serve(receipt({ status: "cancelled" }));
    renderWithClient(<ReceiptView saleId="s1" />);
    await screen.findAllByTestId("invoice-line");
    expect(screen.getAllByText(t.cancelled).length).toBeGreaterThan(0);
    expect(screen.queryByText(t.alreadyPaid)).toBeNull();
    expect(screen.queryByText(t.invoiceRemaining)).toBeNull();
    expect(screen.queryByText(/Arrêtée la présente facture/)).toBeNull();
  });

  it("40 lignes : l'en-tête du tableau se répète, une ligne ne se coupe pas, pages numérotées", async () => {
    serve(receipt({ lines: Array.from({ length: 40 }, (_, index) => line(index)) }));
    const { container } = renderWithClient(<ReceiptView saleId="s1" />);
    const rows = await screen.findAllByTestId("invoice-line");
    expect(rows).toHaveLength(40);
    expect(within(rows[39]!).getByText("40")).toBeInTheDocument();
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

describe("Corrections avant fusion (prompt 35, bloc T)", () => {
  it.each(["a4", "ticket"])(
    "vente annulée (%s) : ni reste à payer, ni somme arrêtée",
    async (chosen) => {
      format = chosen;
      serve(receipt({ status: "cancelled" }));
      renderWithClient(<ReceiptView saleId="s1" />);
      expect(
        await screen.findAllByText(t.cancelled, undefined, { timeout: 5000 }),
      ).not.toHaveLength(0);
      expect(screen.queryByText(t.remaining)).toBeNull();
      expect(screen.queryByText(t.invoiceRemaining)).toBeNull();
      expect(screen.queryByText(/Arrêtée la présente facture/)).toBeNull();
      expect(screen.queryByText(/Reste à payer avant le/)).toBeNull();
    },
  );

  it.each(["a4", "ticket"])(
    "vendeur fait d'espaces (%s) : aucune ligne « Servi par »",
    async (chosen) => {
      format = chosen;
      serve(receipt({ seller_name: "   " }));
      renderWithClient(<ReceiptView saleId="s1" />);
      await screen.findByText("Awa Ndiaye", { exact: false }, { timeout: 5000 });
      expect(screen.queryByText(/Servi par/)).toBeNull();
    },
  );
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

/**
 * Règle mesurable du lot A (ADR 0130) : toute classe de fond de la facture se résout, par
 * `@theme` puis le bloc clair de globals.css (celui de `.papier`), en une couleur de
 * luminance 0,80 au moins ; toute couleur de texte y est lisible (4,5:1) sur chacun de ces
 * fonds. Le logo (une image) n'est pas une classe : il n'est pas compté.
 */
const css = readFileSync(join(__dirname, "..", "..", "..", "..", "globals.css"), "utf8");
const light = css.slice(css.indexOf(":root,"), css.indexOf("\n}", css.indexOf(":root,")));

function resolve(name: string): string | null {
  const theme = new RegExp(`--color-${name}:\\s*var\\(--([a-z0-9-]+)\\)`).exec(css);
  if (!theme?.[1]) return null;
  // `--primary: var(--coges-vert-action)` puis `--coges-vert-action: #117a3c`.
  let variable = theme[1];
  for (let hop = 0; hop < 5; hop++) {
    const value = new RegExp(`--${variable}:\\s*(#[0-9a-f]{6}|var\\(--([a-z0-9-]+)\\))`, "i").exec(
      light,
    );
    if (!value) break;
    if (!value[2]) return value[1]!;
    variable = value[2];
  }
  throw new Error(`jeton ${theme[1]} sans valeur claire`);
}

function colours(root: Element, prefix: "bg" | "text"): Map<string, string> {
  const found = new Map<string, string>();
  for (const element of [root, ...root.querySelectorAll("*")]) {
    for (const cls of element.getAttribute("class")?.split(/\s+/) ?? []) {
      // `even:bg-…`, `print:bg-transparent`, `bg-recu-papier/85`…
      const match = new RegExp(`^(?:[a-z-]+:)*${prefix}-([a-z0-9-]+)(?:/\\d+)?$`).exec(cls);
      if (!match?.[1] || match[1] === "transparent") continue;
      const hex = resolve(match[1]);
      if (hex) found.set(cls, hex);
    }
  }
  return found;
}

describe("facture claire : aucune surface sombre (lot A, ADR 0130)", () => {
  it.each([
    ["payée avec logo", receipt({}, { logo_updated_at: "2026-11-04T09:00:00Z" })],
    ["sans logo, sans client", receipt({ customer: null })],
    ["annulée, avec retours", receipt({ status: "cancelled" })],
  ])("%s", async (_, data) => {
    serve(data);
    renderWithClient(<ReceiptView saleId="s1" />);
    const invoice = await screen.findByRole("article", { name: t.title("1044") });
    const fills = colours(invoice, "bg");
    expect(fills.size).toBeGreaterThan(0);
    for (const [cls, hex] of fills) {
      expect(luminance(hex), `${cls} ${hex}`).toBeGreaterThanOrEqual(0.8);
    }
    const inks = colours(invoice, "text");
    expect(inks.size).toBeGreaterThan(0);
    for (const [cls, ink] of inks) {
      for (const [fill, hex] of [...fills, ["papier", "#ffffff"] as const]) {
        expect(contrast(ink, hex), `${cls} sur ${fill}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
});
