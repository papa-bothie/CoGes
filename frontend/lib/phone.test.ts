import { describe, expect, it } from "vitest";

import { formatPhone, isCompletePhone, phoneDigits } from "./phone";

describe("téléphone", () => {
  it("groupe les chiffres comme la maquette", () => {
    expect(formatPhone("776559021")).toBe("77 655 90 21");
    expect(formatPhone("7765")).toBe("77 65");
    expect(formatPhone("77-655 90.21")).toBe("77 655 90 21");
  });

  it("retire l'indicatif collé et s'arrête à neuf chiffres", () => {
    expect(phoneDigits("+221 77 655 90 21")).toBe("776559021");
    expect(phoneDigits("7765590219999")).toBe("776559021");
  });

  it("accepte un numéro vide ou complet", () => {
    expect(isCompletePhone("")).toBe(true);
    expect(isCompletePhone("77 655 90 21")).toBe(true);
    expect(isCompletePhone("77 655")).toBe(false);
  });
});
