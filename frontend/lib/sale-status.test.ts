import { describe, expect, it } from "vitest";

import { salePill } from "./sale-status";

const BASE = {
  status: "confirmed" as const,
  balance: "0.00",
  debt_status: null,
  has_returns: false,
  returned_total: "0.00",
};

describe("salePill", () => {
  it("dit Payé, Reste, Retour, Annulée et Dette abandonnée", () => {
    expect(salePill(BASE)).toEqual({ status: "paid" });
    expect(salePill({ ...BASE, balance: "10000.00", debt_status: "open" })).toEqual({
      status: "remaining",
      amount: "10 000 F",
    });
    expect(salePill({ ...BASE, has_returns: true, returned_total: "1400.00" })).toEqual({
      status: "returned",
      amount: "1 400 F",
    });
    expect(salePill({ ...BASE, status: "cancelled" })).toEqual({ status: "cancelled" });
    expect(salePill({ ...BASE, balance: "500.00", debt_status: "written_off" })).toEqual({
      status: "writtenOff",
    });
    expect(salePill({ ...BASE, status: "draft" })).toBeNull();
  });
});
