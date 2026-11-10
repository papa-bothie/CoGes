"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Card, Chip, EmptyState, Notice, PageHeader, Pager, Pill, Skeleton } from "@/components/ui";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { SignupRequestPage, SignupStats } from "@/lib/api/schema";
import { formatDateTime } from "@/lib/format";
import { pageOf, withParams } from "@/lib/query";
import { age, requestState } from "@/lib/signup";

const PAGE_SIZE = 20;

/** Filtres de la file : l'équipe d'abord (ce qu'elle doit traiter), puis le reste. */
export const FILTERS = [
  { key: "team", label: "À traiter", query: { status: "pending", path: "team" } },
  { key: "email", label: "Lien e-mail en attente", query: { status: "pending", path: "email" } },
  { key: "activated", label: "Ouvertes", query: { status: "activated" } },
  { key: "rejected", label: "Refusées", query: { status: "rejected" } },
  { key: "abandoned", label: "Abandonnées", query: { status: "abandoned" } },
  { key: "all", label: "Toutes", query: {} },
] as const;

type Query = {
  status?: "pending" | "activated" | "rejected" | "abandoned";
  path?: "email" | "team";
};

export function RequestList() {
  const pathname = usePathname();
  const params = useSearchParams();
  const filter = FILTERS.find((item) => item.key === params.get("file")) ?? FILTERS[0];
  const page = pageOf(params);
  const [data, setData] = useState<SignupRequestPage | null>(null);
  const [stats, setStats] = useState<SignupStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const href = (changes: Record<string, string | null>) => withParams(pathname, params, changes);

  useEffect(() => {
    let alive = true;
    unwrap(
      api.GET("/api/v1/platform/signup-requests", {
        params: { query: { page, page_size: PAGE_SIZE, ...(filter.query as Query) } },
      }),
    ).then(
      (result) => alive && (setData(result), setError(null)),
      (caught: unknown) => alive && setError(errorMessage(caught)),
    );
    return () => {
      alive = false;
    };
  }, [page, filter]);

  useEffect(() => {
    unwrap(
      api.GET("/api/v1/platform/signup-requests/stats", { params: { query: { days: 30 } } }),
    ).then(setStats, () => setStats(null));
  }, []);

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <section aria-labelledby="titre-demandes" className="space-y-5">
      <PageHeader
        id="titre-demandes"
        title="Demandes d'inscription"
        description="Les commerçants qui veulent ouvrir une boutique. Sans e-mail, ou si le lien n'a pas servi, c'est à l'équipe de les contacter et d'ouvrir la boutique."
      />
      {stats && !stats.smtp_configured && (
        <Notice tone="attention">
          L&apos;envoi d&apos;e-mails n&apos;est pas configuré : toutes les demandes passent par
          l&apos;équipe (docs/runbooks/emails.md).
        </Notice>
      )}
      {stats && <StatsCard stats={stats} />}

      <div className="flex flex-wrap gap-2" role="group" aria-label="File">
        {FILTERS.map((option) => (
          <Chip
            key={option.key}
            href={href({ file: option.key === "team" ? null : option.key, page: null })}
            active={filter.key === option.key}
          >
            {option.label}
            {option.key === "team" && data ? ` (${data.team_queue})` : ""}
          </Chip>
        ))}
      </div>

      {error && <Notice tone="danger">{error}</Notice>}
      {!data && !error && <Skeleton label="Chargement des demandes" />}

      {data && (
        <>
          <p className="text-encre-douce" aria-live="polite">
            {data.total} demande{data.total > 1 ? "s" : ""}
          </p>
          {data.items.length === 0 ? (
            <EmptyState title="Aucune demande ici.">Rien à traiter pour l&apos;instant.</EmptyState>
          ) : (
            <ul aria-label="Demandes" className="space-y-3">
              {data.items.map((item) => {
                const state = requestState(item);
                return (
                  <li key={item.id} className="rounded-xl border border-trait bg-surface p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <Link href={`/demandes/${item.id}`} className="font-semibold underline">
                          {item.shop_name ?? "Demande effacée"}
                        </Link>
                        <p className="text-sm text-encre-douce">
                          {[item.full_name, item.phone].filter(Boolean).join(" · ")}
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        {(item.known_accounts ?? []).length > 0 && (
                          <Pill tone="danger">Déjà connu</Pill>
                        )}
                        <Pill tone={state.tone}>{state.label}</Pill>
                      </div>
                    </div>
                    <p className="mt-2 text-sm text-encre-douce">
                      Reçue le {formatDateTime(item.created_at)} · il y a {age(item.created_at)}
                    </p>
                  </li>
                );
              })}
            </ul>
          )}
          <Pager page={page} pages={pages} href={(next) => href({ page: String(next) })} />
        </>
      )}
    </section>
  );
}

function StatsCard({ stats }: { stats: SignupStats }) {
  const rows: [string, number | string][] = [
    ["Reçues avec un e-mail", stats.received_email],
    ["Reçues sans e-mail", stats.received_team],
    ["Ouvertes par le lien", stats.activated_by_link],
    ["Ouvertes par l'équipe", stats.activated_by_team],
    ["Refusées", stats.rejected],
    ["Abandonnées", stats.abandoned],
    [
      "Délai moyen d'ouverture",
      stats.average_hours_to_activation === null ? "—" : `${stats.average_hours_to_activation} h`,
    ],
  ];
  return (
    <Card aria-labelledby="stats-demandes">
      <h2 id="stats-demandes" className="text-lg font-bold">
        Sur les 30 derniers jours
      </h2>
      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt className="text-sm text-encre-douce">{label}</dt>
            <dd className="text-xl font-bold tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}
