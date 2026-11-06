import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { labels } from "@/lib/labels";
import { renderWithClient } from "@/test/render";

import { ShopView } from "./shop-view";

const t = labels.settingsScreens.shop;
let address: string | null = null;
let manager = true;

vi.mock("@/hooks/use-permission", () => ({ usePermission: () => manager }));
vi.mock("@/lib/api/client", () => ({
  api: {
    GET: vi.fn(async () => ({
      id: "c1",
      name: "Boutique",
      slug: "boutique",
      currency: "XOF",
      timezone: "Africa/Dakar",
      settings: {},
      address,
      phone: null,
      wave_number: null,
      ninea: null,
      rc: null,
      receipt_footer: null,
      created_at: "2026-11-04T09:00:00Z",
      updated_at: "2026-11-04T09:00:00Z",
      logo_updated_at: null,
    })),
  },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

describe("Adresse de la boutique (prompt 35, bloc F)", () => {
  it("sans adresse, le gérant est prévenu", async () => {
    address = null;
    manager = true;
    renderWithClient(<ShopView />);
    expect(await screen.findByText(t.addressMissing)).toBeInTheDocument();
  });

  it("avec une adresse, ou sans droit de la changer, rien n'est dit", async () => {
    address = "Rue 10, Dakar";
    manager = true;
    const first = renderWithClient(<ShopView />);
    expect(await screen.findByText(t.title)).toBeInTheDocument();
    expect(screen.queryByText(t.addressMissing)).toBeNull();
    first.unmount();

    address = null;
    manager = false;
    renderWithClient(<ShopView />);
    expect(await screen.findByText(t.title)).toBeInTheDocument();
    expect(screen.queryByText(t.addressMissing)).toBeNull();
  });
});
