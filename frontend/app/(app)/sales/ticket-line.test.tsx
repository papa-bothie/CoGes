import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Schemas } from "@/lib/api/schema";

import { TicketLine } from "./ticket-line";

function line(overrides: Partial<Schemas["SaleItemRead"]> = {}): Schemas["SaleItemRead"] {
  return {
    id: "item-1",
    product_id: "product-1",
    product_name: "Riz 5 kg",
    sku: "ART-0001",
    price_id: null,
    qty: "2.000",
    unit_price: "2500.00",
    list_price: "2500.00",
    price_changed: false,
    price_reason: null,
    unit_cost: "0.0000",
    discount: "0.00",
    tax_rate: "0.0000",
    net_amount: "5000.00",
    tax_amount: "0.00",
    line_total: "5000.00",
    returned_qty: "0.000",
    ...overrides,
  };
}

function setup(item = line()) {
  const onChange = vi.fn();
  render(
    <TicketLine
      item={item}
      currency="XOF"
      disabled={false}
      onChange={onChange}
      onRemove={vi.fn()}
    />,
  );
  return { onChange, user: userEvent.setup() };
}

const usual = (text: string) => text.replace(/[  ]/g, " ");

describe("prix changé sur une ligne (ADR 0107)", () => {
  it("rappelle le prix habituel et envoie le prix tapé avec son motif", async () => {
    const { onChange, user } = setup();
    await user.click(screen.getByRole("button", { name: /changer le prix de riz 5 kg/i }));

    expect(usual(screen.getByText(/prix habituel/i).textContent ?? "")).toContain("2 500");
    const field = screen.getByLabelText("Prix pour cette vente, à l'unité");
    await user.clear(field);
    await user.type(field, "2000");
    await user.click(screen.getByRole("button", { name: "Client fidèle" }));
    await user.click(screen.getByRole("button", { name: "Appliquer ce prix" }));

    expect(onChange).toHaveBeenCalledWith({ unit_price: "2000", price_reason: "Client fidèle" });
  });

  it("demande une seconde confirmation pour offrir l'article", async () => {
    const { onChange, user } = setup();
    await user.click(screen.getByRole("button", { name: /changer le prix/i }));
    const field = screen.getByLabelText("Prix pour cette vente, à l'unité");
    await user.clear(field);
    await user.type(field, "0");
    await user.click(screen.getByRole("button", { name: "Appliquer ce prix" }));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/offert/);
    await user.click(screen.getByRole("button", { name: "Oui, l'offrir" }));
    expect(onChange).toHaveBeenCalledWith({ unit_price: "0", price_reason: "" });
  });

  it("montre « Prix changé » et revient au prix habituel en un geste", async () => {
    const { onChange, user } = setup(
      line({ unit_price: "2000.00", price_changed: true, price_reason: "Prix négocié" }),
    );
    expect(screen.getByText("Prix changé")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /changer le prix/i }));
    await user.click(screen.getByRole("button", { name: /revenir au prix habituel/i }));
    expect(onChange).toHaveBeenCalledWith({ unit_price: "2500.00" });
  });

  it("n'offre pas de retour au prix habituel quand rien n'a changé", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: /changer le prix/i }));
    expect(screen.queryByRole("button", { name: /revenir au prix habituel/i })).toBeNull();
    expect(screen.queryByText("Prix changé")).toBeNull();
  });
});
