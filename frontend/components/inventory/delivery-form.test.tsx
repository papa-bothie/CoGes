import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { renderWithClient } from "@/test/render";

import { DeliveryForm } from "./delivery-form";

const permissions = vi.hoisted(() => ({ create: true }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/inventory/receive",
}));
vi.mock("@/hooks/use-me", () => ({
  useMe: () => ({ data: { company: { id: "boutique" }, user: { id: "awa" } } }),
  useCompanyLocale: () => ({ currency: "XOF", timeZone: "Africa/Dakar" }),
}));
vi.mock("@/hooks/use-permission", () => ({ usePermission: () => permissions.create }));

const RICE = {
  product_id: "riz",
  sku: "ART-0001",
  barcode: "4006381333931",
  name: "Riz 25 kg",
  unit: "sac",
  category_id: null,
  category_name: null,
  is_stock_tracked: true,
  qty_on_hand: "5.000",
  avg_cost: "100.0000",
  last_purchase_cost: "100.0000",
  unit_price: "15500.00",
};

vi.mock("@/lib/api/client", () => ({
  api: {
    GET: vi.fn(async (path: string, init?: { params?: { path?: { code?: string } } }) => {
      if (path === "/api/v1/inventory/products/by-barcode/{code}") {
        const code = init?.params?.path?.code;
        if (code === "4006381333931") return RICE;
        throw new ApiError(404, "product_not_found", "Aucun article ne porte ce code.", {
          code,
          deleted_product: code === "5901234123457",
        });
      }
      return { items: [], page: 1, page_size: 100, total: 0 };
    }),
    POST: vi.fn(),
  },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

const DRAFT_KEY = "coges:draft:v1:boutique:awa:delivery";

/** La douchette tape le code dans la recherche, puis Entrée : la caméra ne s'ouvre pas. */
async function scanWithGun(code: string) {
  const field = screen.getByRole("searchbox", { name: "Chercher un autre article" });
  await userEvent.type(field, `${code}{Enter}`);
}

beforeEach(() => {
  permissions.create = true;
  window.localStorage.clear();
  vi.mocked(api.GET).mockClear();
});

afterEach(() => window.localStorage.clear());

describe("Recevoir une livraison : scan", { timeout: 20_000 }, () => {
  it("ajoute la ligne au premier scan, puis une pièce de plus au second", async () => {
    renderWithClient(<DeliveryForm />);
    await scanWithGun("4006 3813 33931");

    const qty = await screen.findByLabelText("Quantité : Riz 25 kg");
    expect(qty).toHaveValue("1");
    expect(qty).toHaveFocus();
    expect(screen.getByLabelText("Prix d'achat (F) : Riz 25 kg")).toHaveValue("100");
    expect(api.GET).toHaveBeenCalledWith("/api/v1/inventory/products/by-barcode/{code}", {
      params: { path: { code: "4006381333931" } },
    });

    await scanWithGun("4006381333931");
    await waitFor(() => expect(screen.getByLabelText("Quantité : Riz 25 kg")).toHaveValue("2"));
    expect(screen.getAllByLabelText("Quantité : Riz 25 kg")).toHaveLength(1);
    expect(screen.getByText(/était déjà sur la livraison/)).toBeInTheDocument();
  });

  it("dit l'effet exact avant la validation, et garde les lignes dans le brouillon", async () => {
    renderWithClient(<DeliveryForm />);
    await scanWithGun("4006381333931");
    const qty = await screen.findByLabelText("Quantité : Riz 25 kg");
    await userEvent.clear(qty);
    await userEvent.type(qty, "20");

    const effects = screen.getByRole("list", { name: "Après la livraison" });
    expect(effects).toHaveTextContent("Riz 25 kg : 5 → 25");
    expect(screen.getByText(/le prix moyen se recalcule/)).toBeInTheDocument();

    await waitFor(() => {
      const stored = JSON.parse(window.localStorage.getItem(DRAFT_KEY) ?? "{}");
      expect(stored.fields?.lines).toEqual([{ productId: "riz", qty: "20", cost: "100" }]);
    });
  });

  it("un code inconnu propose de créer l'article, avec le code", async () => {
    renderWithClient(<DeliveryForm />);
    await scanWithGun("3017620422003");
    expect(await screen.findByText("Cet article n'existe pas encore. Le créer ?")).toBeVisible();
    expect(screen.getByText("Code-barres : 3017620422003")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Créer l'article" }));
    expect(await screen.findByRole("dialog", { name: "Nouvel article" })).toBeVisible();
    expect(screen.getByLabelText("Quantité reçue")).toHaveValue("1");
  });

  it("sans le droit de créer, renvoie au gérant et montre le code", async () => {
    permissions.create = false;
    renderWithClient(<DeliveryForm />);
    await scanWithGun("3017620422003");
    expect(
      await screen.findByText("Cet article n'existe pas. Demandez au gérant de le créer."),
    ).toBeVisible();
    expect(screen.getByText("Code-barres : 3017620422003")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Créer l'article" })).not.toBeInTheDocument();
  });

  it("un article supprimé est dit tel, sans proposer de le recréer", async () => {
    renderWithClient(<DeliveryForm />);
    await scanWithGun("5901234123457");
    expect(await screen.findByText(/était celui d'un article supprimé/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Créer l'article" })).not.toBeInTheDocument();
  });
});
