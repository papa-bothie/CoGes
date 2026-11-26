"use client";

import { useEffect, useId, useState, type FormEvent } from "react";

import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { PlanRead, SubscriptionDetail } from "@/lib/api/schema";
import { PAYMENT_METHOD_LABELS, SUBSCRIPTION_LABELS, formatDate, formatFcfa } from "@/lib/format";

const TONES: Record<string, string> = {
  trial: "bg-attention-teinte text-attention",
  active: "bg-succes-teinte text-succes",
  past_due: "bg-attention-teinte text-attention",
  suspended: "bg-danger-teinte text-danger",
};

type Method = "wave" | "orange_money" | "cash" | "bank_transfer";
type Months = 1 | 12;

/** Droits qu'un administrateur peut accorder en plus de l'offre (ADR 0132,
 * `plan_features.GRANTABLE`) : ceux que Business réserve. */
export const GRANTABLE_FEATURES: [string, string][] = [
  ["imports", "Import Excel ou CSV"],
  ["priority_support", "Support prioritaire"],
  ["physical_inventory", "Inventaire physique (lot E)"],
  ["invoice_branding", "Facture personnalisée (lot E)"],
  ["stock_locations", "Dépôt et réserve (lot F)"],
];
const FEATURE_NAMES = Object.fromEntries(GRANTABLE_FEATURES);

/** Offre posée par l'administrateur sans être en vente libre (ADR 0132). */
const QUOTED_PLANS = new Set(["premium"]);

/** Le montant attendu par le serveur, ou `""` pour une offre sur devis (montant libre). */
export function expectedAmount(plan: PlanRead, months: Months): string {
  const value = months === 12 ? plan.annual_price_fcfa : plan.price_fcfa;
  return value === null || value === undefined ? "" : String(Math.round(Number(value)));
}

function newKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `paiement-${Date.now()}-${Math.random()}`;
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Abonnement d'une entreprise (ADR 0091, 0132) : offre, statut, échéances, droits acquis,
 * paiements déclarés. L'administrateur change l'offre (vendables, plus Premium sur devis),
 * enregistre un paiement d'un mois ou d'un an (montant prérempli) et accorde des droits
 * acquis avec une raison ; la
 * clé d'idempotence est gardée jusqu'au succès, un second clic ne paie pas deux fois.
 */
export function SubscriptionCard({
  companyId,
  canChange,
  onAccessChanged,
}: {
  companyId: string;
  canChange: boolean;
  onAccessChanged: () => void;
}) {
  const planId = useId();
  const reasonId = useId();
  const amountId = useId();
  const dateId = useId();
  const methodId = useId();
  const noteId = useId();
  const periodId = useId();
  const overrideId = useId();
  const rightsReasonId = useId();
  const [subscription, setSubscription] = useState<SubscriptionDetail | null>(null);
  const [plans, setPlans] = useState<PlanRead[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [planCode, setPlanCode] = useState("");
  const [reason, setReason] = useState("");
  const [planError, setPlanError] = useState<string | null>(null);
  const [amount, setAmount] = useState("");
  const [paidOn, setPaidOn] = useState(today);
  const [method, setMethod] = useState<Method>("wave");
  const [note, setNote] = useState("");
  const [payError, setPayError] = useState<string | null>(null);
  const [paymentKey, setPaymentKey] = useState(newKey);
  const [months, setMonths] = useState<Months>(1);
  const [extra, setExtra] = useState<string[]>([]);
  const [override, setOverride] = useState("");
  const [rightsReason, setRightsReason] = useState("");
  const [rightsError, setRightsError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    Promise.all([
      unwrap(
        api.GET("/api/v1/platform/companies/{company_id}/subscription", {
          params: { path: { company_id: companyId } },
        }),
      ),
      unwrap(api.GET("/api/v1/platform/plans")),
    ]).then(
      ([detail, catalogue]) => {
        if (!alive) return;
        setSubscription(detail);
        setPlans(catalogue);
        setPlanCode(detail.plan.code);
        setAmount(expectedAmount(detail.plan, 1));
        setExtra(detail.extra_features);
        setOverride(detail.max_users_override === null ? "" : String(detail.max_users_override));
      },
      (caught: unknown) => alive && setError(errorMessage(caught)),
    );
    return () => {
      alive = false;
    };
  }, [companyId]);

  if (error) {
    return (
      <p role="alert" className="rounded bg-danger-teinte px-3 py-2 text-danger">
        {error}
      </p>
    );
  }
  if (!subscription) return <p aria-live="polite">Chargement de l&apos;abonnement…</p>;

  const plan = subscription.plan;
  // Les offres en vente, plus Premium sur devis (réservé à l'administrateur, ADR 0132).
  const orderable = plans.filter(
    (candidate) => candidate.is_orderable || QUOTED_PLANS.has(candidate.code),
  );
  const annual = plan.annual_price_fcfa !== null && plan.annual_price_fcfa !== undefined;

  function choosePeriod(next: Months) {
    setMonths(next);
    setAmount(expectedAmount(plan, next));
  }

  async function saveRights(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (rightsReason.trim().length < 3) {
      setRightsError("Donnez la raison du changement.");
      return;
    }
    if (override.trim() !== "" && !/^\d+$/.test(override.trim())) {
      setRightsError("Saisissez un nombre de comptes, ou laissez vide.");
      return;
    }
    setBusy(true);
    try {
      const updated = await unwrap(
        api.PUT("/api/v1/platform/companies/{company_id}/subscription/acquired-rights", {
          params: { path: { company_id: companyId } },
          body: {
            extra_features: extra,
            max_users_override: override.trim() === "" ? null : Number(override.trim()),
            reason: rightsReason.trim(),
          },
        }),
      );
      setSubscription(updated);
      setRightsReason("");
      setRightsError(null);
      setNotice("Droits acquis enregistrés.");
    } catch (caught) {
      setRightsError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }
  const [lastPayment] = subscription.payments;

  async function changePlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (reason.trim().length < 3) {
      setPlanError("Donnez la raison du changement.");
      return;
    }
    setBusy(true);
    try {
      const updated = await unwrap(
        api.PATCH("/api/v1/platform/companies/{company_id}/subscription", {
          params: { path: { company_id: companyId } },
          body: { plan_code: planCode, reason: reason.trim() },
        }),
      );
      setSubscription(updated);
      setReason("");
      setPlanError(null);
      setMonths(1);
      setAmount(expectedAmount(updated.plan, 1));
      setNotice(`Offre changée : ${updated.plan.name}.`);
    } catch (caught) {
      setPlanError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function recordPayment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!/^\d+$/.test(amount.trim()) || Number(amount) <= 0) {
      setPayError("Saisissez un montant en francs CFA, sans décimales.");
      return;
    }
    setBusy(true);
    try {
      const before = subscription?.status;
      const updated = await unwrap(
        api.POST("/api/v1/platform/companies/{company_id}/payments", {
          params: {
            path: { company_id: companyId },
            header: { "Idempotency-Key": paymentKey },
          },
          body: {
            amount_fcfa: amount.trim(),
            // Aujourd'hui : maintenant (midi peut encore être à venir) ; un jour passé : midi.
            paid_at:
              paidOn === today()
                ? new Date().toISOString()
                : new Date(`${paidOn}T12:00:00Z`).toISOString(),
            method,
            note: note.trim() || null,
            period_months: months,
          },
        }),
      );
      setSubscription(updated);
      setPaymentKey(newKey());
      setNote("");
      setPayError(null);
      setNotice(`Paiement enregistré. Payé jusqu'au ${formatDate(updated.current_period_end)}.`);
      if (before !== updated.status) onAccessChanged();
    } catch (caught) {
      setPayError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-labelledby="titre-abonnement"
      className="space-y-4 rounded border border-trait bg-surface p-4"
    >
      <div className="flex flex-wrap items-center gap-3">
        <h2 id="titre-abonnement" className="text-xl font-bold">
          Abonnement
        </h2>
        <span
          className={`rounded px-2 py-0.5 text-sm font-semibold ${TONES[subscription.status] ?? ""}`}
        >
          {SUBSCRIPTION_LABELS[subscription.status] ?? subscription.status}
        </span>
      </div>
      {notice && (
        <p role="status" className="rounded bg-succes-teinte px-3 py-2 text-succes">
          {notice}
        </p>
      )}

      <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-[max-content_1fr]">
        <dt className="text-encre-douce">Offre</dt>
        <dd>
          <span className="font-semibold">{plan.name}</span> ·{" "}
          {plan.price_fcfa === null ? "sur devis" : `${formatFcfa(plan.price_fcfa)} par mois`}
          {subscription.is_license && " · licence sur site"}
        </dd>
        <dt className="text-encre-douce">Comptes actifs</dt>
        <dd>
          {subscription.active_users}
          {subscription.max_users !== null ? ` sur ${subscription.max_users}` : " (sans plafond)"}
        </dd>
        <dt className="text-encre-douce">Droits acquis</dt>
        <dd>
          {subscription.extra_features.length === 0 && subscription.max_users_override === null
            ? "Aucun"
            : [
                ...subscription.extra_features.map((code) => FEATURE_NAMES[code] ?? code),
                ...(subscription.max_users_override !== null
                  ? [`${subscription.max_users_override} comptes`]
                  : []),
              ].join(", ")}
        </dd>
        {subscription.status === "trial" && (
          <>
            <dt className="text-encre-douce">Essai jusqu&apos;au</dt>
            <dd>{formatDate(subscription.trial_ends_at)}</dd>
          </>
        )}
        <dt className="text-encre-douce">Payé jusqu&apos;au</dt>
        <dd>
          {subscription.current_period_end ? formatDate(subscription.current_period_end) : "—"}
        </dd>
        <dt className="text-encre-douce">Dernier paiement</dt>
        <dd>
          {lastPayment
            ? `${formatFcfa(lastPayment.amount_fcfa)} le ${formatDate(lastPayment.paid_at)} (${PAYMENT_METHOD_LABELS[lastPayment.method] ?? lastPayment.method})`
            : "Aucun"}
        </dd>
      </dl>

      {canChange && (
        <div className="grid gap-6 md:grid-cols-2">
          <form onSubmit={changePlan} className="space-y-3" aria-labelledby="titre-offre">
            <h3 id="titre-offre" className="font-bold">
              Changer d&apos;offre
            </h3>
            <div className="space-y-1">
              <label htmlFor={planId} className="block font-semibold">
                Offre
              </label>
              <select
                id={planId}
                value={planCode}
                onChange={(event) => setPlanCode(event.target.value)}
                className="w-full rounded border border-trait bg-surface px-3 py-2"
              >
                {orderable.map((candidate) => (
                  <option key={candidate.code} value={candidate.code}>
                    {candidate.name} —{" "}
                    {candidate.price_fcfa === null ? "sur devis" : formatFcfa(candidate.price_fcfa)}
                    , jusqu&apos;à {candidate.max_users ?? "∞"} utilisateurs
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <label htmlFor={reasonId} className="block font-semibold">
                Raison
              </label>
              <input
                id={reasonId}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                className="w-full rounded border border-trait bg-surface px-3 py-2"
              />
            </div>
            {planError && (
              <p role="alert" className="rounded bg-danger-teinte px-3 py-2 text-danger">
                {planError}
              </p>
            )}
            <button
              type="submit"
              disabled={busy || planCode === plan.code}
              className="rounded bg-accent px-4 py-2 font-semibold text-accent-encre disabled:opacity-50"
            >
              Changer d&apos;offre
            </button>
          </form>

          <form onSubmit={recordPayment} className="space-y-3" aria-labelledby="titre-paiement">
            <h3 id="titre-paiement" className="font-bold">
              Enregistrer un paiement
            </h3>
            <div className="space-y-1">
              <label htmlFor={periodId} className="block font-semibold">
                Durée
              </label>
              <select
                id={periodId}
                value={months}
                onChange={(event) => choosePeriod(Number(event.target.value) as Months)}
                className="w-full rounded border border-trait bg-surface px-3 py-2"
              >
                <option value={1}>1 mois</option>
                {(annual || plan.price_fcfa === null) && <option value={12}>1 an (-10 %)</option>}
              </select>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1">
                <label htmlFor={amountId} className="block font-semibold">
                  Montant (FCFA)
                </label>
                <input
                  id={amountId}
                  inputMode="numeric"
                  value={amount}
                  onChange={(event) => setAmount(event.target.value)}
                  className="w-full rounded border border-trait bg-surface px-3 py-2"
                />
              </div>
              <div className="space-y-1">
                <label htmlFor={dateId} className="block font-semibold">
                  Date
                </label>
                <input
                  id={dateId}
                  type="date"
                  max={today()}
                  value={paidOn}
                  onChange={(event) => setPaidOn(event.target.value)}
                  className="w-full rounded border border-trait bg-surface px-3 py-2"
                />
              </div>
            </div>
            <div className="space-y-1">
              <label htmlFor={methodId} className="block font-semibold">
                Moyen
              </label>
              <select
                id={methodId}
                value={method}
                onChange={(event) => setMethod(event.target.value as Method)}
                className="w-full rounded border border-trait bg-surface px-3 py-2"
              >
                {Object.entries(PAYMENT_METHOD_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <label htmlFor={noteId} className="block font-semibold">
                Note
              </label>
              <input
                id={noteId}
                value={note}
                onChange={(event) => setNote(event.target.value)}
                className="w-full rounded border border-trait bg-surface px-3 py-2"
              />
            </div>
            {payError && (
              <p role="alert" className="rounded bg-danger-teinte px-3 py-2 text-danger">
                {payError}
              </p>
            )}
            <button
              type="submit"
              disabled={busy}
              className="rounded bg-accent px-4 py-2 font-semibold text-accent-encre disabled:opacity-50"
            >
              Enregistrer le paiement
            </button>
          </form>

          <form
            onSubmit={saveRights}
            className="space-y-3 md:col-span-2"
            aria-labelledby="titre-droits"
          >
            <h3 id="titre-droits" className="font-bold">
              Droits acquis
            </h3>
            <fieldset className="space-y-1">
              <legend className="font-semibold">En plus de l&apos;offre</legend>
              {GRANTABLE_FEATURES.map(([code, label]) => (
                <label key={code} className="flex min-h-11 items-center gap-2">
                  <input
                    type="checkbox"
                    checked={extra.includes(code)}
                    onChange={(event) =>
                      setExtra((current) =>
                        event.target.checked
                          ? [...current, code]
                          : current.filter((item) => item !== code),
                      )
                    }
                    className="size-5"
                  />
                  {label}
                </label>
              ))}
            </fieldset>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1">
                <label htmlFor={overrideId} className="block font-semibold">
                  Plafond de comptes acquis (vide : celui de l&apos;offre)
                </label>
                <input
                  id={overrideId}
                  inputMode="numeric"
                  value={override}
                  onChange={(event) => setOverride(event.target.value)}
                  className="w-full rounded border border-trait bg-surface px-3 py-2"
                />
              </div>
              <div className="space-y-1">
                <label htmlFor={rightsReasonId} className="block font-semibold">
                  Raison des droits acquis
                </label>
                <input
                  id={rightsReasonId}
                  value={rightsReason}
                  onChange={(event) => setRightsReason(event.target.value)}
                  className="w-full rounded border border-trait bg-surface px-3 py-2"
                />
              </div>
            </div>
            {rightsError && (
              <p role="alert" className="rounded bg-danger-teinte px-3 py-2 text-danger">
                {rightsError}
              </p>
            )}
            <button
              type="submit"
              disabled={busy}
              className="rounded bg-accent px-4 py-2 font-semibold text-accent-encre disabled:opacity-50"
            >
              Enregistrer les droits acquis
            </button>
          </form>
        </div>
      )}

      {subscription.payments.length > 0 && (
        <div className="space-y-2">
          <h3 className="font-bold">Paiements déclarés</h3>
          <div className="overflow-x-auto rounded border border-trait">
            <table className="w-full text-left">
              <thead className="border-b border-trait text-sm text-encre-douce">
                <tr>
                  <th scope="col" className="px-3 py-2">
                    Date
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Montant
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Durée
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Moyen
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Note
                  </th>
                </tr>
              </thead>
              <tbody>
                {subscription.payments.map((payment) => (
                  <tr key={payment.id} className="border-b border-trait last:border-0">
                    <td className="px-3 py-2">{formatDate(payment.paid_at)}</td>
                    <td className="px-3 py-2">{formatFcfa(payment.amount_fcfa)}</td>
                    <td className="px-3 py-2">
                      {payment.period_months === 12 ? "1 an" : "1 mois"}
                    </td>
                    <td className="px-3 py-2">
                      {PAYMENT_METHOD_LABELS[payment.method] ?? payment.method}
                    </td>
                    <td className="px-3 py-2">{payment.note ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {subscription.payments_total > subscription.payments.length && (
            <p className="text-encre-douce">
              {subscription.payments.length} plus récents sur {subscription.payments_total}.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
