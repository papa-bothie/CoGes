import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import { labels } from "@/lib/labels";
import { renderWithClient } from "@/test/render";

import { LogoField, logoRefusal } from "./logo-field";

const t = labels.settingsScreens.shop.logo;
const ok = (data: unknown = null) => ({ data, error: undefined, response: new Response(null) });

vi.mock("@/lib/api/client", () => ({
  api: { GET: vi.fn(), PUT: vi.fn(), DELETE: vi.fn() },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

beforeEach(() => {
  vi.mocked(api.GET)
    .mockReset()
    .mockResolvedValue(ok(new Blob(["png"], { type: "image/png" })) as never);
  vi.mocked(api.PUT)
    .mockReset()
    .mockResolvedValue(ok() as never);
  vi.mocked(api.DELETE)
    .mockReset()
    .mockResolvedValue(ok() as never);
});

const file = (type: string, size = 10) =>
  new File([new Uint8Array(size)], "logo", { type, lastModified: 0 });

describe("Logo de la boutique (prompt 35, bloc L)", () => {
  it("refuse avant l'envoi ce que le serveur refuserait", () => {
    expect(logoRefusal(file("image/png"))).toBeNull();
    expect(logoRefusal(file("image/jpeg"))).toBeNull();
    expect(logoRefusal(file("image/webp"))).toBeNull();
    expect(logoRefusal(file("image/svg+xml"))).toBe(t.unsupported);
    expect(logoRefusal(file("image/gif"))).toBe(t.unsupported);
    expect(logoRefusal({ type: "image/png", size: 2 * 1024 * 1024 + 1 })).toBe(t.tooLarge);
  });

  it("sans logo : rien n'est lu, « Ajouter le logo » envoie le fichier", async () => {
    renderWithClient(<LogoField version={null} canEdit />);
    expect(screen.getByText(t.none)).toBeInTheDocument();
    expect(api.GET).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: t.remove })).toBeNull();

    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    await userEvent.upload(input, file("image/png"));
    await waitFor(() => expect(api.PUT).toHaveBeenCalledTimes(1));
    const call = vi.mocked(api.PUT).mock.calls[0] as unknown as [string, { body: FormData }];
    expect(call[0]).toBe("/api/v1/companies/me/logo");
    expect(call[1].body.get("file")).toBeInstanceOf(File);
  });

  it("un SVG n'est jamais envoyé, et le refus est dit en clair", async () => {
    renderWithClient(<LogoField version={null} canEdit />);
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    await userEvent.upload(input, file("image/svg+xml"), { applyAccept: false });
    expect(await screen.findByText(t.unsupported)).toBeInTheDocument();
    expect(api.PUT).not.toHaveBeenCalled();
  });

  it("avec logo : aperçu par une adresse data:, « Changer » et « Retirer »", async () => {
    renderWithClient(<LogoField version="2026-11-04T10:00:00Z" canEdit />);
    const image = await screen.findByRole("img", { name: t.preview });
    expect(image.getAttribute("src")).toMatch(/^data:image\/png;base64,/);
    expect(vi.mocked(api.GET).mock.calls[0]?.[0]).toBe("/api/v1/companies/me/logo");
    expect(screen.getByRole("button", { name: t.change })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: t.remove }));
    await waitFor(() => expect(api.DELETE).toHaveBeenCalledWith("/api/v1/companies/me/logo"));
  });

  it("sans droit : l'aperçu seul, aucun bouton", async () => {
    renderWithClient(<LogoField version="2026-11-04T10:00:00Z" canEdit={false} />);
    expect(await screen.findByRole("img", { name: t.preview })).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
