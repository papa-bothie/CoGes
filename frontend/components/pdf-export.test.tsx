import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import { saveBlob } from "@/lib/files";
import { labels } from "@/lib/labels";
import { MAX_PDF_DAYS, pdfPeriod } from "@/lib/pdf-export";
import { renderWithClient } from "@/test/render";

import { AccountantExports, PdfExport } from "./pdf-export";

const t = labels.pdfExport;
let permissions: string[] = [];

vi.mock("@/hooks/use-me", () => ({
  useMe: () => ({ data: { permissions } }),
  useCompanyLocale: () => ({ currency: "XOF", timeZone: "Africa/Dakar" }),
}));
vi.mock("@/hooks/use-permission", async () => {
  const { can } = await import("@/lib/permissions");
  return { usePermission: (rule: never) => can(permissions, rule) };
});
vi.mock("@/lib/files", async (original) => ({
  ...(await original<typeof import("@/lib/files")>()),
  saveBlob: vi.fn(),
}));
vi.mock("@/lib/api/client", () => ({
  api: { GET: vi.fn(), POST: vi.fn() },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

const PDF = new Blob(["%PDF-1.4"], { type: "application/pdf" });

beforeEach(() => {
  permissions = [];
  vi.mocked(saveBlob).mockClear();
  vi.mocked(api.GET)
    .mockReset()
    .mockResolvedValue({
      data: PDF,
      error: undefined,
      response: new Response(null, {
        headers: { "Content-Disposition": 'attachment; filename="Stock-2026-11-04-Boutique.pdf"' },
      }),
    } as never);
  vi.mocked(api.POST)
    .mockReset()
    .mockResolvedValue({ data: {}, error: undefined, response: new Response(null) } as never);
});

describe("pdfPeriod (prompt 35, bloc X)", () => {
  it("aujourd'hui, cette semaine depuis lundi, ce mois depuis le 1er", () => {
    // Le 4 novembre 2026 est un mercredi.
    expect(pdfPeriod("day", "2026-11-04")).toEqual({ from: "2026-11-04", to: "2026-11-04" });
    expect(pdfPeriod("week", "2026-11-04")).toEqual({ from: "2026-11-02", to: "2026-11-04" });
    expect(pdfPeriod("week", "2026-11-08")).toEqual({ from: "2026-11-02", to: "2026-11-08" });
    expect(pdfPeriod("month", "2026-11-04")).toEqual({ from: "2026-11-01", to: "2026-11-04" });
  });

  it("des dates choisies : dans l'ordre, 366 jours au plus", () => {
    const today = "2026-11-04";
    expect(pdfPeriod("custom", today, { from: "2026-01-01", to: "2026-12-31" })).toEqual({
      from: "2026-01-01",
      to: "2026-12-31",
    });
    expect(pdfPeriod("custom", today, { from: "2026-11-05", to: "2026-11-04" })).toBeNull();
    expect(pdfPeriod("custom", today, { from: "", to: "2026-11-04" })).toBeNull();
    expect(MAX_PDF_DAYS).toBe(366);
    expect(pdfPeriod("custom", today, { from: "2025-11-03", to: "2026-11-04" })).toBeNull();
  });
});

describe("Exporter en PDF", () => {
  it("masqué sans le droit de lecture et le droit d'export", () => {
    permissions = ["inventory:read"];
    renderWithClient(<PdfExport kind="stock" />);
    expect(screen.queryByRole("button", { name: t.button })).toBeNull();
  });

  it("l'état du stock se télécharge tout de suite, sous le nom du serveur", async () => {
    permissions = ["inventory:read", "analytics:export"];
    renderWithClient(<PdfExport kind="stock" rubrique="stock" />);
    await userEvent.click(screen.getByRole("button", { name: t.button }));
    await waitFor(() =>
      expect(saveBlob).toHaveBeenCalledWith(PDF, "Stock-2026-11-04-Boutique.pdf"),
    );
    expect(vi.mocked(api.GET).mock.calls[0]?.[0]).toBe("/api/v1/analytics/stock/pdf");
  });

  it("les ventes partent au worker avec une clé d'idempotence, puis le lien vers Fichiers", async () => {
    permissions = ["sales:read", "sales:export"];
    renderWithClient(<PdfExport kind="sales" />);
    await userEvent.click(screen.getByRole("button", { name: t.button }));
    await userEvent.click(screen.getByRole("button", { name: t.choices.day }));
    await userEvent.click(screen.getByRole("button", { name: t.prepare }));
    await waitFor(() => expect(api.POST).toHaveBeenCalled());
    const [path, init] = vi.mocked(api.POST).mock.calls[0] as unknown as [
      string,
      {
        body: { kind: string; date_from: string; date_to: string };
        headers: Record<string, string>;
      },
    ];
    expect(path).toBe("/api/v1/exports/pdf");
    expect(init.body.kind).toBe("sales");
    expect(init.body.date_from).toBe(init.body.date_to);
    expect(init.headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(await screen.findByRole("link", { name: t.files })).toHaveAttribute(
      "href",
      "/settings/files",
    );
  });

  it("des dates inversées sont refusées sans appel", async () => {
    permissions = ["expenses:read", "analytics:export"];
    renderWithClient(<PdfExport kind="expenses" />);
    await userEvent.click(screen.getByRole("button", { name: t.button }));
    await userEvent.click(screen.getByRole("button", { name: t.choices.custom }));
    await userEvent.type(screen.getByLabelText(t.from), "2026-11-05");
    await userEvent.type(screen.getByLabelText(t.to), "2026-11-01");
    await userEvent.click(screen.getByRole("button", { name: t.download }));
    expect(await screen.findByText(t.invalidPeriod)).toBeInTheDocument();
    expect(api.GET).not.toHaveBeenCalled();
  });

  it("un état du stock trop long passe par la file : « Préparer le PDF », puis Fichiers", async () => {
    permissions = ["inventory:read", "analytics:export"];
    vi.mocked(api.GET).mockResolvedValue({
      data: undefined,
      error: {
        error: {
          code: "report_too_large",
          message: "Ce document est trop long pour être fait tout de suite.",
          details: { kind: "stock", rows: 3200, limit: 1000 },
        },
      },
      response: new Response(null, { status: 409 }),
    } as never);
    renderWithClient(<PdfExport kind="stock" rubrique="stock" />);
    await userEvent.click(screen.getByRole("button", { name: t.button }));
    expect(await screen.findByText(t.tooLarge(3200).replace(/\s+/g, " "))).toBeInTheDocument();
    expect(saveBlob).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: t.prepare }));
    await waitFor(() => expect(api.POST).toHaveBeenCalled());
    const [path, init] = vi.mocked(api.POST).mock.calls[0] as unknown as [
      string,
      { body: Record<string, string>; headers: Record<string, string> },
    ];
    expect(path).toBe("/api/v1/exports/pdf");
    expect(init.body).toEqual({ kind: "stock" });
    expect(init.headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(await screen.findByRole("link", { name: t.files })).toHaveAttribute(
      "href",
      "/settings/files",
    );
  });

  it("des dépenses trop longues gardent leur période en passant par la file", async () => {
    permissions = ["expenses:read", "analytics:export"];
    vi.mocked(api.GET).mockResolvedValue({
      data: undefined,
      error: {
        error: {
          code: "report_too_large",
          message: "Trop long.",
          details: { kind: "expenses", rows: 1500, limit: 1000 },
        },
      },
      response: new Response(null, { status: 409 }),
    } as never);
    renderWithClient(<PdfExport kind="expenses" />);
    await userEvent.click(screen.getByRole("button", { name: t.button }));
    await userEvent.click(screen.getByRole("button", { name: t.choices.day }));
    await userEvent.click(screen.getByRole("button", { name: t.download }));
    expect(await screen.findByText(t.tooLarge(1500).replace(/\s+/g, " "))).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: t.prepare }));
    await waitFor(() => expect(api.POST).toHaveBeenCalled());
    const body = (vi.mocked(api.POST).mock.calls[0]![1] as { body: Record<string, string> }).body;
    expect(body.kind).toBe("expenses");
    expect(body.date_from).toBe(body.date_to);
    expect(await screen.findByRole("status")).toHaveTextContent(t.queued);
  });

  it("« Pour votre comptable » ne montre que les exports permis, et rien sans aucun", () => {
    permissions = ["analytics:read", "analytics:export"];
    const { unmount } = renderWithClient(<AccountantExports kinds={["sales", "cash"]} />);
    expect(screen.getByText(t.titles.cash)).toBeInTheDocument();
    expect(screen.queryByText(t.titles.sales)).toBeNull();
    unmount();
    permissions = [];
    renderWithClient(<AccountantExports kinds={["sales", "cash"]} />);
    expect(screen.queryByText(t.section)).toBeNull();
  });
});
