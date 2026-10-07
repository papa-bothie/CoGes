import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SalePaymentBadge } from "./status-badge";

describe("SalePaymentBadge", () => {
  it("dit « Payé » quand plus rien n'est dû", () => {
    render(<SalePaymentBadge sale={{ status: "confirmed", balance: "0.00", debt_status: "paid" }} />);
    expect(screen.getByText("Payé")).toHaveAttribute("data-variant", "success");
  });

  it("dit ce qui reste, en orange", () => {
    render(
      <SalePaymentBadge
        sale={{ status: "confirmed", balance: "10000.00", debt_status: "partially_paid" }}
      />,
    );
    expect(screen.getByText("Reste 10 000 FCFA")).toHaveAttribute("data-variant", "warning");
  });

  it("ne réclame pas une dette abandonnée", () => {
    render(
      <SalePaymentBadge
        sale={{ status: "confirmed", balance: "10000.00", debt_status: "written_off" }}
      />,
    );
    expect(screen.getByText("Dette abandonnée")).toHaveAttribute("data-variant", "neutral");
    expect(screen.queryByText(/Reste/)).not.toBeInTheDocument();
  });

  it("ne dit rien d'un brouillon ni d'une vente annulée", () => {
    const { container, rerender } = render(
      <SalePaymentBadge sale={{ status: "draft", balance: "5000.00", debt_status: null }} />,
    );
    expect(container).toBeEmptyDOMElement();
    rerender(
      <SalePaymentBadge sale={{ status: "cancelled", balance: "5000.00", debt_status: null }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
