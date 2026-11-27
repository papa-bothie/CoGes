import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlanRead, SubscriptionDetail } from "@/lib/api/schema";

import { SubscriptionCard } from "./subscription-card";

const PLANS: PlanRead[] = [
  {
    id: "1",
    code: "starter",
    name: "Pro",
    price_fcfa: "4900.00",
    annual_price_fcfa: "52920.00",
    max_users: 3,
    features: [],
    is_orderable: true,
  },
  {
    id: "2",
    code: "business",
    name: "Business",
    price_fcfa: "9900.00",
    annual_price_fcfa: "106920.00",
    max_users: 7,
    features: [],
    is_orderable: true,
  },
  {
    id: "3",
    code: "premium",
    name: "Premium",
    price_fcfa: null,
    annual_price_fcfa: null,
    max_users: 10,
    features: [],
    is_orderable: false,
  },
  {
    id: "4",
    code: "sur_devis",
    name: "Sur devis",
    price_fcfa: null,
    annual_price_fcfa: null,
    max_users: null,
    features: [],
    is_orderable: false,
  },
];

const DETAIL: SubscriptionDetail = {
  company_id: "c",
  plan: PLANS[0]!,
  status: "trial",
  trial_ends_at: "2026-11-23T10:00:00Z",
  started_at: "2026-10-24T10:00:00Z",
  current_period_end: null,
  active_users: 2,
  is_license: false,
  extra_features: [],
  max_users_override: null,
  max_users: 3,
  reminder_stage: null,
  reminder_for_end: null,
  reminder_at: null,
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
const PUT = vi.fn();

vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  api: {
    GET: (...args: unknown[]) => GET(...args),
    PATCH: (...args: unknown[]) => PATCH(...args),
    POST: (...args: unknown[]) => POST(...args),
    PUT: (...args: unknown[]) => PUT(...args),
  },
}));

beforeEach(() => {
  GET.mockReset().mockImplementation(async (path: string) =>
    ok(path.endsWith("/plans") ? PLANS : DETAIL),
  );
  PATCH.mockReset();
  POST.mockReset();
  PUT.mockReset();
});

describe("carte abonnement", () => {
  it("montre l'offre, l'essai, les offres vendables et Premium sur devis", async () => {
    render(<SubscriptionCard companyId="c" canChange onAccessChanged={() => undefined} />);
    expect(await screen.findByText("Pro")).toBeVisible();
    expect(screen.getByText(/4.900.FCFA par mois/)).toBeVisible();
    expect(screen.getByText("2 sur 3")).toBeVisible();
    expect(screen.getByText("23/11/2026")).toBeVisible();
    const offers = Array.from(
      (screen.getByLabelText("Offre") as HTMLSelectElement).options,
      (option) => option.textContent ?? "",
    );
    expect(offers.map((text) => text.split(" —")[0])).toEqual(["Pro", "Business", "Premium"]);
    expect(offers[2]).toContain("sur devis");
    expect(screen.getAllByText("Aucun")).toHaveLength(2); // droits acquis, dernier paiement
  });

  it("un an préremplit le montant annuel et l'envoie avec 12 mois", async () => {
    POST.mockResolvedValue(
      ok({ ...DETAIL, status: "active", current_period_end: "2027-11-26T10:00:00Z" }, 201),
    );
    render(<SubscriptionCard companyId="c" canChange onAccessChanged={() => undefined} />);
    const amount = await screen.findByLabelText("Montant (FCFA)");
    expect(amount).toHaveValue("4900");
    await userEvent.selectOptions(screen.getByLabelText("Durée"), "12");
    expect(amount).toHaveValue("52920");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer le paiement" }));
    await screen.findByText(/Paiement enregistré/);
    const body = POST.mock.calls[0]?.[1].body;
    expect([body.amount_fcfa, body.period_months]).toEqual(["52920", 12]);
  });

  it("les droits acquis s'affichent et s'enregistrent avec une raison", async () => {
    GET.mockImplementation(async (path: string) =>
      ok(
        path.endsWith("/plans")
          ? PLANS
          : { ...DETAIL, extra_features: ["imports"], max_users_override: 5, max_users: 5 },
      ),
    );
    PUT.mockResolvedValue(ok({ ...DETAIL, extra_features: [], max_users_override: null }));
    render(<SubscriptionCard companyId="c" canChange onAccessChanged={() => undefined} />);
    expect(await screen.findByText("Import Excel ou CSV, 5 comptes")).toBeVisible();
    expect(screen.getByText("2 sur 5")).toBeVisible();
    const imports = screen.getByRole("checkbox", { name: "Import Excel ou CSV" });
    expect(imports).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les droits acquis" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Donnez la raison");
    await userEvent.click(imports);
    await userEvent.clear(screen.getByLabelText(/Plafond de comptes acquis/));
    await userEvent.type(screen.getByLabelText("Raison des droits acquis"), "Fin du geste");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les droits acquis" }));
    await screen.findByText("Droits acquis enregistrés.");
    expect(PUT.mock.calls[0]?.[1].body).toEqual({
      extra_features: [],
      max_users_override: null,
      reason: "Fin du geste",
    });
  });

  it("une descente refusée dit combien désactiver", async () => {
    PATCH.mockResolvedValue(
      refused(409, "plan_downgrade_too_many_users", "Désactivez-en 2 avant de changer d'offre."),
    );
    GET.mockImplementation(async (path: string) =>
      ok(path.endsWith("/plans") ? PLANS : { ...DETAIL, plan: PLANS[1]!, max_users: 7 }),
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
    expect(POST.mock.calls[0]?.[1].body.amount_fcfa).toBe("4900");
    expect(changed).toHaveBeenCalledOnce();
  });

  it("dit la relance envoyée pour cette fin, et prolonge avec une raison (ADR 0133)", async () => {
    GET.mockImplementation(async (path: string) =>
      ok(
        path.endsWith("/plans")
          ? PLANS
          : {
              ...DETAIL,
              status: "past_due",
              reminder_stage: "due",
              reminder_for_end: DETAIL.trial_ends_at,
              reminder_at: "2026-11-23T06:30:00Z",
            },
      ),
    );
    POST.mockResolvedValue(
      ok({ ...DETAIL, trial_ends_at: "2026-11-30T10:00:00Z", reminder_stage: null }),
    );
    render(<SubscriptionCard companyId="c" canChange onAccessChanged={() => undefined} />);
    expect(await screen.findByTestId("relance-etape")).toHaveTextContent(
      "Jour J (grâce) (envoyé le 23/11/2026)",
    );
    await userEvent.click(screen.getByRole("button", { name: "Prolonger" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("raison");
    expect(POST).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText("Raison de la prolongation"), "Voyage du gérant");
    await userEvent.click(screen.getByRole("button", { name: "Prolonger" }));
    await screen.findByText(/Prolongé de 7 jours : nouvelle fin le 30\/11\/2026/);
    const [path, request] = POST.mock.calls[0] ?? [];
    expect(path).toBe("/api/v1/platform/companies/{company_id}/subscription/extend");
    expect(request.body).toEqual({ days: 7, reason: "Voyage du gérant" });
  });

  it("le support lit sans formulaire", async () => {
    render(<SubscriptionCard companyId="c" canChange={false} onAccessChanged={() => undefined} />);
    await screen.findByText("Pro");
    expect(screen.queryByRole("button", { name: "Enregistrer le paiement" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Enregistrer les droits acquis" })).toBeNull();
  });
});
