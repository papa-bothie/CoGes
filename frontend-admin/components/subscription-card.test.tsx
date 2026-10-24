import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlanRead, SubscriptionDetail } from "@/lib/api/schema";

import { SubscriptionCard } from "./subscription-card";

const PLANS: PlanRead[] = [
  {
    id: "1",
    code: "starter",
    name: "Starter",
    price_fcfa: "4900.00",
    max_users: 3,
    features: [],
    is_orderable: true,
  },
  {
    id: "2",
    code: "business",
    name: "Business",
    price_fcfa: "9900.00",
    max_users: 7,
    features: [],
    is_orderable: true,
  },
  {
    id: "3",
    code: "premium",
    name: "Premium",
    price_fcfa: "14900.00",
    max_users: 10,
    features: [],
    is_orderable: true,
  },
  {
    id: "4",
    code: "sur_devis",
    name: "Sur devis",
    price_fcfa: null,
    max_users: null,
    features: [],
    is_orderable: false,
  },
];

const DETAIL: SubscriptionDetail = {
  company_id: "c",
  plan: PLANS[2]!,
  status: "trial",
  trial_ends_at: "2026-11-23T10:00:00Z",
  started_at: "2026-10-24T10:00:00Z",
  current_period_end: null,
  active_users: 5,
  payments: [],
  payments_total: 0,
};

const ok = (data: unknown, status = 200) => ({ data, response: new Response(null, { status }) });
const refused = (status: number, code: string, message: string) => ({
  error: { error: { code, message, details: {} } },
  response: new Response(null, { status }),
});

const GET = vi.fn();
const PATCH = vi.fn();
const POST = vi.fn();

vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  api: {
    GET: (...args: unknown[]) => GET(...args),
    PATCH: (...args: unknown[]) => PATCH(...args),
    POST: (...args: unknown[]) => POST(...args),
  },
}));

beforeEach(() => {
  GET.mockReset().mockImplementation(async (path: string) =>
    ok(path.endsWith("/plans") ? PLANS : DETAIL),
  );
  PATCH.mockReset();
  POST.mockReset();
});

describe("carte abonnement", () => {
  it("montre l'offre, l'essai et seulement les offres vendables", async () => {
    render(<SubscriptionCard companyId="c" canChange onAccessChanged={() => undefined} />);
    expect(await screen.findByText("Premium")).toBeVisible();
    expect(screen.getByText(/14.900.FCFA par mois/)).toBeVisible();
    expect(screen.getByText("5 sur 10")).toBeVisible();
    expect(screen.getByText("23/11/2026")).toBeVisible();
    const options = screen.getAllByRole("option").map((option) => option.textContent);
    expect(options.some((text) => text?.startsWith("Sur devis"))).toBe(false);
  });

  it("une descente refusée dit combien désactiver", async () => {
    PATCH.mockResolvedValue(
      refused(409, "plan_downgrade_too_many_users", "Désactivez-en 2 avant de changer d'offre."),
    );
    render(<SubscriptionCard companyId="c" canChange onAccessChanged={() => undefined} />);
    await userEvent.selectOptions(await screen.findByLabelText("Offre"), "starter");
    await userEvent.type(screen.getByLabelText("Raison"), "Le client veut payer moins");
    await userEvent.click(screen.getByRole("button", { name: "Changer d'offre" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Désactivez-en 2");
  });

  it("garde la clé du paiement jusqu'au succès, puis en tire une autre", async () => {
    POST.mockResolvedValueOnce(
      refused(503, "server_error", "Le serveur n'a pas pu répondre."),
    ).mockResolvedValueOnce(
      ok({ ...DETAIL, status: "active", current_period_end: "2026-11-24T10:00:00Z" }, 201),
    );
    const changed = vi.fn();
    render(<SubscriptionCard companyId="c" canChange onAccessChanged={changed} />);
    const submit = await screen.findByRole("button", { name: "Enregistrer le paiement" });
    await userEvent.click(submit);
    await screen.findByRole("alert");
    await userEvent.click(submit);
    await screen.findByText(/Paiement enregistré/);
    const keys = POST.mock.calls.map((call) => call[1].params.header["Idempotency-Key"]);
    expect(keys[0]).toBe(keys[1]);
    expect(POST.mock.calls[0]?.[1].body.amount_fcfa).toBe("14900");
    expect(changed).toHaveBeenCalledOnce();
  });

  it("le support lit sans formulaire", async () => {
    render(<SubscriptionCard companyId="c" canChange={false} onAccessChanged={() => undefined} />);
    await screen.findByText("Premium");
    expect(screen.queryByRole("button", { name: "Enregistrer le paiement" })).toBeNull();
  });
});
