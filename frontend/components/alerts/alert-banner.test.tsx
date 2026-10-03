import { render, screen } from "@testing-library/react";
import { AlertTriangle } from "lucide-react";
import { describe, expect, it } from "vitest";

import { AlertBanner } from "./alert-banner";

describe("AlertBanner", () => {
  it("prend le ton « attention » (orange) par défaut", () => {
    render(<AlertBanner icon={AlertTriangle} title="Dette échue (5)" />);
    const banner = screen.getByRole("status");
    expect(banner).toHaveAttribute("data-severity", "warning");
    expect(banner.className).toContain("bg-warning/5");
    expect(banner.className).toContain("text-warning-ink");
    expect(banner.className).not.toMatch(/destructive|bg-card/);
  });

  it("passe en « danger » (rouge) seulement si le serveur dit critical", () => {
    render(
      <AlertBanner
        icon={AlertTriangle}
        title="Rupture de stock — Riz"
        href="/inventory"
        severity="critical"
      />,
    );
    const banner = screen.getByRole("link", { name: /Rupture de stock/ });
    expect(banner).toHaveAttribute("data-severity", "critical");
    expect(banner.className).toContain("bg-destructive/5");
    expect(banner.className).toContain("text-danger-ink");
    expect(banner.className).not.toContain("warning");
  });
});
