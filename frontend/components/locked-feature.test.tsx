import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LockedFeatureCard } from "./locked-feature";

describe("fonction verrouillée (prompt 41, B4)", () => {
  it("badge Business, « Disponible avec Business » et le bouton WhatsApp", () => {
    render(<LockedFeatureCard title="Ajouter beaucoup d'articles" description="Texte" />);
    expect(screen.getByText("Business")).toBeInTheDocument();
    expect(screen.getByText("Disponible avec Business")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Passer à Business" });
    expect(decodeURIComponent(link.getAttribute("href")!)).toContain(
      "Je veux passer à CoGes Business.",
    );
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });
});
