import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import { labels } from "@/lib/labels";
import { renderWithClient } from "@/test/render";

import { RightsView } from "./rights-view";

const t = labels.settingsScreens.rights;

vi.mock("@/hooks/use-permission", () => ({ usePermission: () => true }));
vi.mock("@/lib/api/client", () => ({
  api: {
    GET: vi.fn(async () => ({
      abilities: [
        { key: "base", label: "Accueil", permissions: [], locked: true },
        { key: "sell", label: "Vendre", permissions: [], locked: false },
        { key: "stock", label: "Corriger le stock", permissions: [], locked: false },
      ],
      roles: [
        {
          role_id: "r-vendeur",
          name: "vendeur",
          label: "Vendeur",
          locked: false,
          abilities: ["base", "sell"],
          partial: ["stock"],
        },
      ],
    })),
    // L'enregistrement reste en cours : seul compte l'affichage optimiste.
    PUT: vi.fn(() => new Promise(() => undefined)),
  },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

describe("Qui peut faire quoi (prompt 32, D4)", () => {
  it("une ligne « en partie » complétée ne l'est plus tout de suite, sans attendre le serveur", async () => {
    renderWithClient(<RightsView />);
    expect(await screen.findByText(t.partialHint)).toBeInTheDocument();
    // La grille existe en tableau et en liste (téléphone) : la première suffit.
    const [cell] = screen.getAllByRole("button", {
      name: t.partialAria("Corriger le stock", "Vendeur"),
    });
    await userEvent.click(cell!);
    expect(api.PUT).toHaveBeenCalled();
    for (const ticked of screen.getAllByRole("button", {
      name: t.aria("Corriger le stock", "Vendeur"),
    })) {
      expect(ticked).toHaveAttribute("aria-pressed", "true");
    }
    expect(screen.queryByText(t.partialHint)).toBeNull();
  });
});
