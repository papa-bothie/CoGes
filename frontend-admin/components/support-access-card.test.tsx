import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SupportSessionList, SupportSessionRead } from "@/lib/api/schema";

import { openMerchantTab, SupportAccessCard } from "./support-access-card";

const SESSION: SupportSessionRead = {
  id: "s1",
  company_id: "c",
  opened_by: "Awa Ndiaye",
  opened_by_me: true,
  justification: "Le gérant signale un écart de caisse",
  started_at: "2026-10-24T10:00:00Z",
  expires_at: "2099-10-24T12:00:00Z",
  ended_at: null,
  is_open: true,
};

const ok = (data: unknown, status = 200) => ({ data, response: new Response(null, { status }) });

let listing: SupportSessionList = { active: null, recent: [] };
const GET = vi.fn();
const POST = vi.fn();
const DELETE = vi.fn();

vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  api: {
    GET: (...args: unknown[]) => GET(...args),
    POST: (...args: unknown[]) => POST(...args),
    DELETE: (...args: unknown[]) => DELETE(...args),
  },
}));

beforeEach(() => {
  listing = { active: null, recent: [] };
  GET.mockReset().mockImplementation(async () => ok(listing));
  POST.mockReset();
  DELETE.mockReset();
});

function renderCard(suspended = false) {
  render(<SupportAccessCard companyId="c" suspended={suspended} merchantUrl="https://coges.sn/" />);
}

describe("carte accès support (ADR 0092)", () => {
  it("exige un motif avant d'ouvrir, 2 h par défaut", async () => {
    renderCard();
    expect(await screen.findByLabelText("Durée")).toHaveValue("120");
    await userEvent.click(screen.getByRole("button", { name: "Ouvrir un accès support" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("pourquoi");
    expect(POST).not.toHaveBeenCalled();
  });

  it("ouvre avec le motif et la durée choisie, puis montre la session", async () => {
    POST.mockImplementation(async () => {
      listing = { active: SESSION, recent: [SESSION] };
      return ok(
        { session: SESSION, access_token: "t", token_type: "bearer", expires_in: 3600 },
        201,
      );
    });
    renderCard();
    await userEvent.type(
      await screen.findByLabelText("Pourquoi cet accès ?"),
      SESSION.justification!,
    );
    await userEvent.selectOptions(screen.getByLabelText("Durée"), "60");
    await userEvent.click(screen.getByRole("button", { name: "Ouvrir un accès support" }));
    expect(POST.mock.calls[0]?.[1].body).toEqual({
      justification: SESSION.justification,
      duration_minutes: 60,
    });
    expect(await screen.findByText(/Accès ouvert par vous/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Voir l'entreprise" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Fermer l'accès" })).toBeVisible();
  });

  it("la session d'un collègue se ferme mais ne s'emprunte pas", async () => {
    listing = { active: { ...SESSION, opened_by_me: false }, recent: [] };
    renderCard();
    expect(await screen.findByText(/Accès ouvert par Awa Ndiaye/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Voir l'entreprise" })).toBeNull();
    DELETE.mockImplementation(async () => {
      listing = { active: null, recent: [] };
      return ok(null, 204);
    });
    await userEvent.click(screen.getByRole("button", { name: "Fermer l'accès" }));
    expect(await screen.findByText("Accès support fermé.")).toBeVisible();
  });

  it("une entreprise suspendue ne propose pas d'ouvrir", async () => {
    renderCard(true);
    expect(await screen.findByText(/suspendue/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Ouvrir un accès support" })).toBeNull();
  });

  it("met le jeton dans le fragment et détache l'onglet", async () => {
    const tab = { opener: {} as unknown, location: { href: "" }, close: vi.fn() };
    const open = vi.fn(() => tab as unknown as Window);
    await openMerchantTab(
      "https://coges.sn/",
      async () => ({ access_token: "abc", expires_in: 7200 }),
      open,
    );
    expect(open).toHaveBeenCalledWith("about:blank");
    expect(tab.opener).toBeNull();
    expect(tab.location.href).toBe("https://coges.sn/support#token=abc&expires_in=7200");
  });
});
