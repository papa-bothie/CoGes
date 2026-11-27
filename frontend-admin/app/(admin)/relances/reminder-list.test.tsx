import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReminderItem } from "@/lib/api/schema";

import { ReminderList } from "./reminder-list";

const GET = vi.fn();
vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  api: { GET: (...args: unknown[]) => GET(...args) },
}));

const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });

function item(overrides: Partial<ReminderItem> = {}): ReminderItem {
  return {
    company_id: "c1",
    name: "Keur Fatou",
    slug: "keur-fatou",
    status: "past_due",
    kind: "trial",
    stage: "last",
    sent_stage: "due",
    ends_at: "2026-12-10T12:00:00Z",
    pause_on: "2026-12-13",
    plan_name: "Pro",
    message: "Bonjour, c'est l'équipe CoGes pour Keur Fatou. Dernier rappel : …",
    contacts: [
      { full_name: "Fatou Sall", phone: "+221770000001" },
      { full_name: "Sans numéro", phone: null },
    ],
    ...overrides,
  };
}

beforeEach(() => GET.mockReset());

describe("À relancer (ADR 0133)", () => {
  it("l'étape, la fin, la pause, ce qui est déjà parti, et WhatsApp par gérant", async () => {
    GET.mockResolvedValue(ok({ computed_at: "2026-12-12T07:00:00Z", items: [item()] }));
    render(<ReminderList />);
    const card = (await screen.findByRole("heading", { name: "Keur Fatou" })).closest("section")!;
    const scope = within(card);
    expect(scope.getByText("Dernier rappel")).toBeVisible();
    expect(
      scope.getByText(/Essai gratuit · fin le 10\/12\/2026 · pause prévue le 13\/12\/2026/),
    ).toBeVisible();
    expect(scope.getByText("Déjà envoyé : jour j (grâce)")).toBeVisible();
    const links = scope.getAllByRole("link", { name: /Écrire sur WhatsApp/ });
    expect(links).toHaveLength(1); // le gérant sans numéro n'a pas de lien
    const url = new URL(links[0]!.getAttribute("href")!);
    expect(url.pathname).toBe("/221770000001");
    expect(url.searchParams.get("text")).toContain("Dernier rappel");
  });

  it("le message se modifie avant l'envoi", async () => {
    GET.mockResolvedValue(ok({ computed_at: "2026-12-12T07:00:00Z", items: [item()] }));
    render(<ReminderList />);
    const field = await screen.findByLabelText("Message WhatsApp (modifiable)");
    await userEvent.clear(field);
    await userEvent.type(field, "Bonjour Fatou");
    const link = screen.getByRole("link", { name: /Écrire sur WhatsApp/ });
    expect(new URL(link.getAttribute("href")!).searchParams.get("text")).toBe("Bonjour Fatou");
  });

  it("personne à relancer", async () => {
    GET.mockResolvedValue(ok({ computed_at: "2026-12-12T07:00:00Z", items: [] }));
    render(<ReminderList />);
    expect(await screen.findByText("Personne à relancer aujourd'hui.")).toBeVisible();
  });
});
