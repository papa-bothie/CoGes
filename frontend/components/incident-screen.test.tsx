import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";

import { IncidentScreen } from "./incident-screen";

describe("écran d'incident (ADR 0085)", () => {
  it("rassure, donne la référence et place le focus sur le titre", () => {
    const error = new ApiError(500, "server_error", "détail interne", {}, "ab12cd34-0000-0000");
    render(<IncidentScreen error={error} onRetry={() => {}} />);

    const title = screen.getByRole("heading", { level: 1, name: "Un souci de notre côté" });
    expect(title).toHaveFocus();
    expect(
      screen.getByText("Vos données sont en sécurité. Réessayez dans un instant."),
    ).toBeVisible();
    expect(screen.getByText("AB12 CD34")).toBeVisible();
    expect(screen.queryByText("détail interne")).toBeNull();
    expect(screen.getByRole("link", { name: "Retour à l'accueil" })).toHaveAttribute(
      "href",
      "/dashboard",
    );
  });

  it("réessaie à la demande", async () => {
    const retry = vi.fn();
    render(<IncidentScreen error={new Error("boum")} onRetry={retry} />);
    expect(screen.queryByText("boum")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Réessayer" }));
    expect(retry).toHaveBeenCalledOnce();
  });
});
