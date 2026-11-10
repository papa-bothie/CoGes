import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AcceptanceForm } from "@/app/(auth)/acceptation/acceptance-form";
import { legalDocument } from "@/lib/legal/documents";
import { parseLegal } from "@/lib/legal/parse";

import { LegalMarkdown } from "./legal-markdown";

vi.mock("@/lib/api/client", () => ({
  api: {
    POST: vi.fn(async () => ({ data: undefined, response: new Response(null, { status: 204 }) })),
  },
  unwrap: async (call: Promise<{ data: unknown }>) => (await call).data,
}));
vi.mock("@/lib/auth/session", () => ({ logout: vi.fn(async () => undefined) }));

describe("rendu des textes légaux (ADR 0117)", () => {
  it("rend titres, gras, listes et tableaux sans HTML brut", () => {
    const doc = parseLegal(
      [
        "<!-- version: 2026-12-01 -->",
        "# Titre",
        "",
        "## 1. Offres",
        "",
        "Prix **TVA non applicable** et l'apostrophe.",
        "",
        "- un ;",
        "- deux.",
        "",
        "| Offre | Prix |",
        "| --- | --- |",
        "| Starter | 4 900 F CFA |",
        "",
        "<script>alert(1)</script>",
      ].join("\n"),
    );
    const { container } = render(<LegalMarkdown tokens={doc.tokens} />);
    expect(screen.getByRole("heading", { level: 2, name: "1. Offres" })).toHaveAttribute(
      "id",
      "1-offres",
    );
    expect(screen.getByText("TVA non applicable").tagName).toBe("STRONG");
    expect(screen.getByText(/l'apostrophe/)).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    const region = screen.getByRole("region", { name: "1. Offres" });
    expect(region).toHaveAttribute("tabindex", "0");
    const table = within(region).getByRole("table");
    expect(within(table).getByRole("columnheader", { name: "Prix" })).toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "4 900 F CFA" })).toBeInTheDocument();
    // Le HTML du texte n'est jamais injecté.
    expect(container.querySelector("script")).toBeNull();
  });

  it("refuse un élément non prévu plutôt que de l'afficher à moitié", () => {
    const doc = parseLegal("<!-- version: 2026-12-01 -->\n# T\n\n> citation\n");
    expect(() => render(<LegalMarkdown tokens={doc.tokens} />)).toThrow(/non pris en charge/);
  });

  it("les deux vrais textes se rendent en entier", () => {
    for (const slug of ["conditions", "confidentialite"] as const) {
      const { unmount } = render(<LegalMarkdown tokens={legalDocument(slug).tokens} />);
      expect(screen.getAllByRole("table").length).toBeGreaterThan(0);
      unmount();
    }
  });
});

describe("« Avant de continuer »", () => {
  it("le bouton reste inactif tant que la case n'est pas cochée", async () => {
    const user = userEvent.setup();
    const onDone = vi.fn();
    render(<AcceptanceForm onDone={onDone} />);
    const button = screen.getByRole("button", { name: "Accepter et continuer" });
    expect(button).toBeDisabled();
    expect(screen.getByText("Cochez la case pour continuer.")).toBeInTheDocument();

    const box = screen.getByRole("checkbox", { name: /J'ai lu et j'accepte/ });
    await user.click(box);
    expect(button).toBeEnabled();
    await user.click(box);
    expect(button).toBeDisabled();

    await user.click(box);
    await user.click(button);
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("les deux liens ouvrent les textes dans un nouvel onglet", () => {
    render(<AcceptanceForm />);
    expect(
      screen.getByRole("link", { name: /Lire les conditions d'utilisation et de vente/ }),
    ).toHaveAttribute("href", "/conditions");
    expect(screen.getByRole("link", { name: /politique de confidentialité/ })).toHaveAttribute(
      "target",
      "_blank",
    );
  });
});
