import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Money } from "./money";

describe("Money", () => {
  it("élargit l'espace des milliers à l'écran sans changer le texte", () => {
    const { container } = render(<Money value="13000.00" currency="XOF" />);
    // Le texte reste « 13 000 FCFA » (espace fine insécable) : copier-coller et tests identiques.
    expect(container.textContent).toBe("13 000 FCFA");
    // Le séparateur est isolé pour être élargi par l'interlettrage.
    expect(container.querySelectorAll("span span")).toHaveLength(1);
  });

  it("laisse un montant sans milliers tel quel", () => {
    const { container } = render(<Money value="500" currency="XOF" />);
    expect(container.textContent).toBe("500 FCFA");
    expect(container.querySelectorAll("span span")).toHaveLength(0);
  });
});
