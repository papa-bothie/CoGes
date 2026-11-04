import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { labels } from "@/lib/labels";
import { renderWithClient } from "@/test/render";

import { ReturnSlipView } from "./return-slip-view";

vi.mock("@/hooks/use-me", () => ({
  useCompanyLocale: () => ({ currency: "XOF", timeZone: "Africa/Dakar" }),
}));
vi.mock("@/lib/api/client", () => ({
  api: {
    GET: vi.fn(async (path: string) => {
      if (path.endsWith("/logo"))
        return {
          data: new Blob(["png"], { type: "image/png" }),
          error: undefined,
          response: new Response(null),
        };
      if (path.startsWith("/api/v1/sale-returns"))
        return {
          id: "r1",
          sale_id: "s1",
          return_no: "R-000007",
          reason: "Abîmé",
          returned_at: "2026-11-04T12:00:00Z",
          total_refund: "1500.00",
          refunded_total: "0.00",
          waived_total: "0.00",
          refund_status: "pending",
          refund_due: "1500.00",
          items: [],
          payments: [],
        };
      if (path.endsWith("/receipt"))
        return {
          sale_no: "V-001044",
          customer: null,
          company: {
            name: "Boutique Keur Fatou",
            currency: "XOF",
            address: "Rue 10, Médina, Dakar",
            phone: "77 123 45 67",
            logo_updated_at: "2026-11-04T09:00:00Z",
          },
        };
      return { id: "s1", items: [] };
    }),
  },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

describe("Bon de retour (prompt 35, bloc F)", () => {
  it("même en-tête que le ticket : logo en noir et blanc, nom, adresse", async () => {
    renderWithClient(<ReturnSlipView returnId="r1" />);
    const logo = await screen.findByRole("img", {
      name: labels.receipt.logoAlt("Boutique Keur Fatou"),
    });
    expect(logo).toHaveClass("grayscale");
    expect(screen.getByText("Rue 10, Médina, Dakar")).toBeInTheDocument();
    expect(screen.getByText(labels.receipt.slip.heading)).toBeInTheDocument();
  });
});
