"use client";

import { useEffect, useId, useState, type FormEvent } from "react";

import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { RevenueRead, SignupsRead, StatsOverview } from "@/lib/api/schema";
import { formatDateTime, formatFcfa } from "@/lib/format";
import {
  GRANULARITIES,
  REVENUE_PERIODS,
  barHeight,
  bucketLabel,
  bucketTitle,
  formatDay,
  formatSpan,
  type Granularity,
  type RevenuePeriod,
} from "@/lib/stats";

type RevenueQuery =
  { period: "current_month" | "previous_month" } | { period: "custom"; start: string; end: string };

/** Aujourd'hui à Dakar (à l'heure de Greenwich toute l'année), en `aaaa-mm-jj`. */
function todayInDakar(): string {
  return new Date().toISOString().slice(0, 10);
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count > 1 ? "s" : ""}`;
}

/** Choix exclusifs en boutons radio : lisibles au clavier, annoncés comme un groupe. */
function Choices<T extends string>({
  legend,
  name,
  options,
  value,
  onChange,
}: {
  legend: string;
  name: string;
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <fieldset className="flex flex-wrap gap-2">
      <legend className="sr-only">{legend}</legend>
      {options.map((option) => (
        <label
          key={option.value}
          className={`cursor-pointer rounded border px-3 py-1.5 text-sm font-semibold has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent ${
            value === option.value
              ? "border-accent bg-accent text-accent-encre"
              : "border-trait bg-surface text-encre"
          }`}
        >
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={value === option.value}
            onChange={() => onChange(option.value)}
            className="sr-only"
          />
          {option.label}
        </label>
      ))}
    </fieldset>
  );
}

function Overview({ overview }: { overview: StatsOverview }) {
  const { companies } = overview;
  const tiles = [
    { label: "Entreprises", value: companies.total },
    { label: "En essai", value: companies.trial },
    { label: "Actives", value: companies.active },
    { label: "Suspendues", value: companies.suspended },
    { label: "Utilisateurs actifs", value: overview.active_users },
  ];
  return (
    <>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {tiles.map((tile) => (
          <div key={tile.label} className="rounded border border-trait bg-surface px-4 py-3">
            <dt className="text-sm text-encre-douce">{tile.label}</dt>
            <dd className="text-2xl font-bold tabular-nums">{tile.value}</dd>
          </div>
        ))}
      </dl>

      <section aria-labelledby="titre-offres" className="space-y-2">
        <h2 id="titre-offres" className="text-xl font-bold">
          Entreprises par offre
        </h2>
        <p className="text-encre-douce">
          D&apos;après l&apos;abonnement. Les essais, tous sur Premium, sont comptés à part des
          entreprises payantes.
        </p>
        <div className="overflow-x-auto rounded border border-trait bg-surface">
          <table className="w-full text-left">
            <thead className="border-b border-trait text-sm text-encre-douce">
              <tr>
                <th scope="col" className="px-3 py-2">
                  Offre
                </th>
                <th scope="col" className="px-3 py-2 text-right">
                  En essai
                </th>
                <th scope="col" className="px-3 py-2 text-right">
                  Payantes
                </th>
                <th scope="col" className="px-3 py-2 text-right">
                  Suspendues
                </th>
                <th scope="col" className="px-3 py-2 text-right">
                  Total
                </th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {overview.plans.map((plan) => (
                <tr key={plan.code} className="border-b border-trait last:border-0">
                  <th scope="row" className="px-3 py-2 font-semibold">
                    {plan.name}
                  </th>
                  <td className="px-3 py-2 text-right">{plan.trial}</td>
                  <td className="px-3 py-2 text-right">{plan.paying}</td>
                  <td className="px-3 py-2 text-right">{plan.suspended}</td>
                  <td className="px-3 py-2 text-right font-semibold">{plan.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {overview.without_subscription > 0 && (
          <p role="status" className="rounded bg-attention-teinte px-3 py-2 text-attention">
            {plural(overview.without_subscription, "entreprise")} sans abonnement.
          </p>
        )}
      </section>
    </>
  );
}

function Revenue({ round }: { round: number }) {
  const startId = useId();
  const endId = useId();
  const [period, setPeriod] = useState<RevenuePeriod>("current_month");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [query, setQuery] = useState<RevenueQuery | null>({ period: "current_month" });
  const [revenue, setRevenue] = useState<RevenueRead | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (query === null) return;
    let alive = true;
    unwrap(api.GET("/api/v1/platform/stats/revenue", { params: { query } })).then(
      (result) => alive && (setRevenue(result), setError(null)),
      (caught: unknown) => alive && (setRevenue(null), setError(errorMessage(caught))),
    );
    return () => {
      alive = false;
    };
  }, [query, round]);

  function choose(next: RevenuePeriod) {
    setPeriod(next);
    // Une période personnalisée attend ses deux dates ; les autres partent tout de suite.
    setQuery(next === "custom" ? null : { period: next });
    if (next === "custom") setRevenue(null);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    setQuery({ period: "custom", start, end });
  }

  const today = todayInDakar();
  return (
    <section aria-labelledby="titre-revenu" className="space-y-3">
      <h2 id="titre-revenu" className="text-xl font-bold">
        Revenu
      </h2>
      <p className="text-encre-douce">
        Basé sur les paiements enregistrés, pas sur les offres en cours : seul l&apos;argent déclaré
        reçu compte.
      </p>
      <Choices
        legend="Période du revenu"
        name="periode-revenu"
        options={REVENUE_PERIODS}
        value={period}
        onChange={choose}
      />
      {period === "custom" && (
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <label htmlFor={startId} className="block font-semibold">
              Du
            </label>
            <input
              id={startId}
              type="date"
              required
              max={today}
              value={start}
              onChange={(event) => setStart(event.target.value)}
              className="rounded border border-trait bg-surface px-3 py-2"
            />
          </div>
          <div className="space-y-1">
            <label htmlFor={endId} className="block font-semibold">
              Au
            </label>
            <input
              id={endId}
              type="date"
              required
              max={today}
              value={end}
              onChange={(event) => setEnd(event.target.value)}
              className="rounded border border-trait bg-surface px-3 py-2"
            />
          </div>
          <button
            type="submit"
            className="rounded bg-accent px-4 py-2 font-semibold text-accent-encre"
          >
            Afficher
          </button>
          <p className="w-full text-sm text-encre-douce">
            366 jours au plus, jusqu&apos;à aujourd&apos;hui.
          </p>
        </form>
      )}
      {error && (
        <p role="alert" className="rounded bg-danger-teinte px-3 py-2 text-danger">
          {error}
        </p>
      )}
      {revenue && (
        <div className="rounded border border-trait bg-surface px-4 py-3" aria-live="polite">
          <p className="text-3xl font-bold tabular-nums">{formatFcfa(revenue.total_fcfa)}</p>
          <p>
            {plural(revenue.payment_count, "paiement")} enregistré
            {revenue.payment_count > 1 ? "s" : ""} {formatSpan(revenue.start, revenue.end)}
          </p>
          <p className="text-sm text-encre-douce">
            Jours comptés en entier, heure de Dakar. Calculé le{" "}
            {formatDateTime(revenue.computed_at)}.
          </p>
        </div>
      )}
    </section>
  );
}

function Signups({ round }: { round: number }) {
  const [granularity, setGranularity] = useState<Granularity>("month");
  const [signups, setSignups] = useState<SignupsRead | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    unwrap(api.GET("/api/v1/platform/stats/signups", { params: { query: { granularity } } })).then(
      (result) => alive && (setSignups(result), setError(null)),
      (caught: unknown) => alive && setError(errorMessage(caught)),
    );
    return () => {
      alive = false;
    };
  }, [granularity, round]);

  const shown = signups?.granularity === granularity ? signups : null;
  const max = shown ? Math.max(...shown.buckets.map((bucket) => bucket.count)) : 0;
  const first = shown?.buckets[0];
  const last = shown?.buckets[shown.buckets.length - 1];
  return (
    <section aria-labelledby="titre-inscriptions" className="space-y-3">
      <h2 id="titre-inscriptions" className="text-xl font-bold">
        Nouvelles entreprises
      </h2>
      <Choices
        legend="Regroupement"
        name="regroupement"
        options={GRANULARITIES}
        value={granularity}
        onChange={setGranularity}
      />
      {error && (
        <p role="alert" className="rounded bg-danger-teinte px-3 py-2 text-danger">
          {error}
        </p>
      )}
      {shown && first && last && (
        <>
          <p className="text-encre-douce">
            {plural(shown.total, "entreprise")} créée{shown.total > 1 ? "s" : ""}{" "}
            {formatSpan(first.start, last.end)} (entreprises supprimées exclues, heure de Dakar). La
            dernière période est en cours.
          </p>
          <div className="rounded border border-trait bg-surface px-3 pt-3 pb-2" aria-hidden="true">
            <div className="flex h-40 items-end gap-px">
              {shown.buckets.map((bucket) => (
                <div
                  key={bucket.start}
                  title={`${bucketTitle(bucket, granularity)} : ${bucket.count}`}
                  className="flex h-full flex-1 flex-col justify-end"
                >
                  {granularity === "month" && bucket.count > 0 && (
                    <span className="text-center text-xs tabular-nums">{bucket.count}</span>
                  )}
                  <div
                    className="rounded-t bg-accent"
                    style={{ height: `${barHeight(bucket.count, max)}%` }}
                  />
                </div>
              ))}
            </div>
            <div className="mt-1 flex gap-px border-t border-trait pt-1 text-xs text-encre-douce">
              {shown.buckets.map((bucket, index) => (
                <span key={bucket.start} className="flex-1 truncate text-center">
                  {granularity === "month" || index % 4 === 0
                    ? bucketLabel(bucket, granularity)
                    : ""}
                </span>
              ))}
            </div>
          </div>
          <details className="rounded border border-trait bg-surface">
            <summary className="cursor-pointer px-3 py-2 font-semibold">Voir les chiffres</summary>
            <table className="w-full text-left">
              <caption className="sr-only">
                Nouvelles entreprises {granularity === "month" ? "par mois" : "par semaine"}
              </caption>
              <thead className="border-y border-trait text-sm text-encre-douce">
                <tr>
                  <th scope="col" className="px-3 py-2">
                    Période
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Nouvelles entreprises
                  </th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {[...shown.buckets].reverse().map((bucket) => (
                  <tr key={bucket.start} className="border-b border-trait last:border-0">
                    <th scope="row" className="px-3 py-1.5 font-normal">
                      {granularity === "month"
                        ? `${bucketTitle(bucket, granularity)} (${formatDay(bucket.start)} – ${formatDay(bucket.end)})`
                        : bucketTitle(bucket, granularity)}
                    </th>
                    <td className="px-3 py-1.5 text-right">{bucket.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </section>
  );
}

export function StatsDashboard() {
  const [overview, setOverview] = useState<StatsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [round, setRound] = useState(0);

  useEffect(() => {
    let alive = true;
    unwrap(api.GET("/api/v1/platform/stats/overview")).then(
      (result) => alive && (setOverview(result), setError(null)),
      (caught: unknown) => alive && setError(errorMessage(caught)),
    );
    return () => {
      alive = false;
    };
  }, [round]);

  return (
    <section aria-labelledby="titre-stats" className="space-y-8">
      <div className="space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h1 id="titre-stats" className="text-2xl font-bold">
            Statistiques
          </h1>
          <p className="text-encre-douce">
            {overview ? `Comptés le ${formatDateTime(overview.computed_at)}` : "Calcul…"}
            <button
              type="button"
              onClick={() => setRound((value) => value + 1)}
              className="ml-3 rounded border border-trait px-3 py-1.5 text-sm font-semibold text-encre"
            >
              Actualiser
            </button>
          </p>
        </div>
        {error && (
          <p role="alert" className="rounded bg-danger-teinte px-3 py-2 text-danger">
            {error}
          </p>
        )}
        {overview && <Overview overview={overview} />}
      </div>
      <Revenue round={round} />
      <Signups round={round} />
    </section>
  );
}
