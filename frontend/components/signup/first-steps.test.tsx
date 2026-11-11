import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FirstSteps } from "./first-steps";

describe("premiers pas d'une boutique neuve (ADR 0118)", () => {
  it("trois gestes, dans l'ordre, chacun vers son écran", () => {
    render(<FirstSteps visible={() => true} />);
    const links = screen.getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/products/new",
      "/customers/new",
      "/sales/new",
    ]);
  });

  it("un geste interdit n'est pas proposé ; aucun permis : rien", () => {
    const { rerender } = render(<FirstSteps visible={(href) => href === "/sales/new"} />);
    expect(screen.getAllByRole("link")).toHaveLength(1);
    rerender(<FirstSteps visible={() => false} />);
    expect(screen.queryByRole("region")).toBeNull();
    expect(screen.queryByText("Pour bien démarrer")).toBeNull();
  });
});
