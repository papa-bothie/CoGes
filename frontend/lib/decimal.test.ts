import { describe, expect, it } from "vitest";

import {
  compareDecimal,
  sumDecimals,
  parseDecimalInput,
  percentToRate,
  rateToPercent,
  subtractDecimal,
  toInputDecimal,
} from "./decimal";

describe("compareDecimal", () => {
  it("compare des échelles différentes sans float", () => {
    expect(compareDecimal("3.000", "3")).toBe(0);
    expect(compareDecimal("2.999", "3")).toBe(-1);
    expect(compareDecimal("10", "9.5")).toBe(1);
    expect(compareDecimal("0.1", "0.10000000000000000001")).toBe(-1);
  });

  it("gère les négatifs et refuse l'illisible", () => {
    expect(compareDecimal("-1", "0")).toBe(-1);
    expect(compareDecimal("abc", "1")).toBeNull();
  });
});

describe("parseDecimalInput", () => {
  it("accepte la virgule française et refuse le reste", () => {
    expect(parseDecimalInput(" 1,5 ")).toBe("1.5");
    expect(parseDecimalInput("12 000")).toBe("12000");
    expect(parseDecimalInput("-2")).toBeNull();
    expect(parseDecimalInput("")).toBeNull();
  });
});

describe("toInputDecimal", () => {
  it("retire les zéros inutiles et passe à la virgule", () => {
    expect(toInputDecimal("12.500")).toBe("12,5");
    expect(toInputDecimal("3.000")).toBe("3");
    expect(toInputDecimal("1500.00")).toBe("1500");
    expect(toInputDecimal("10")).toBe("10");
  });
});

describe("subtractDecimal", () => {
  it("soustrait sans float, à l'échelle la plus fine", () => {
    expect(subtractDecimal("5.000", "3.000")).toBe("2.000");
    expect(subtractDecimal("0.3", "0.1")).toBe("0.2");
    expect(subtractDecimal("1", "2.5")).toBe("-1.5");
    expect(subtractDecimal("x", "1")).toBeNull();
  });
});

describe("taux en pourcentage", () => {
  it("convertit la saisie en fraction sans float", () => {
    expect(percentToRate("18")).toBe("0.18");
    expect(percentToRate("5,5")).toBe("0.055");
    expect(percentToRate("0")).toBe("0");
    expect(percentToRate("100")).toBe("1");
    expect(percentToRate("abc")).toBeNull();
  });

  it("affiche la fraction de l'API en pourcentage", () => {
    expect(rateToPercent("0.1800")).toBe("18");
    expect(rateToPercent("0.0550")).toBe("5,5");
    expect(rateToPercent("0.0000")).toBe("0");
  });
});

describe("sumDecimals", () => {
  it("additionne sans float, retenues comprises", () => {
    expect(sumDecimals(["62000.00", "71500.00", "0.10", "0.20"])).toBe("133500.30");
    expect(sumDecimals([])).toBe("0");
    expect(sumDecimals(["1", "abc"])).toBeNull();
  });
});
