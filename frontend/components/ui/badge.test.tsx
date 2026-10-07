import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Badge } from "./badge";
import { buttonVariants } from "./button";

describe("Badge de statut", () => {
  it("reste teinté, jamais plein comme un bouton primaire", () => {
    render(<Badge variant="info">Confirmée</Badge>);
    const badge = screen.getByText("Confirmée");
    expect(badge.className).toContain("bg-ventes-teinte");
    expect(badge.className).not.toContain(buttonVariants({ variant: "default" }).split(" ")[0]);
    expect(badge.className).not.toMatch(/\bbg-primary\b(?!\/)/);
  });
});
