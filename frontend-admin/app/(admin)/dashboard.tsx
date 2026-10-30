"use client";

import { CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useSystemHealth } from "@/components/system-health";
import { Card, Notice, PageHeader } from "@/components/ui";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { AttentionRead, StatsOverview, TeamSummary } from "@/lib/api/schema";
import { formatDate, formatDateTime } from "@/lib/format";
import { securityEventText, securityEventTone } from "@/lib/security";

type Tile = { label: string; value: number; href: string };

function Tiles({ title, tiles, computedAt }: { title: string; tiles: Tile[]; computedAt: string }) {
  const id = `tuiles-${title}`;
  return (
    <section aria-labelledby={id} className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id={id} className="text-lg font-bold">
          {title}
        </h2>
        <p className="text-sm text-encre-douce">Compté le {formatDateTime(computedAt)}</p>
      </div>
      <ul className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {tiles.map((tile) => (
          <li key={tile.label}>
            <Link
              href={tile.href}
              className="block h-full rounded-xl border border-trait bg-surface p-4 hover:border-champ hover:bg-voile"
            >
              <span className="block text-3xl font-bold tabular-nums">{tile.value}</span>
              <span className="mt-1 block text-encre-douce">{tile.label}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** « À traiter » (prompt 27, D1.6) : visible dès l'ouverture, sans naviguer. */
function ToHandle({ attention }: { attention: AttentionRead }) {
  const { state } = useSystemHealth();
  const items: { key: string; text: string; href: string; tone: "danger" | "attention" }[] = [];
  if (state.kind === "down") {
    items.push({
      key: "systeme",
      text: `Le système est en panne (${state.health.problems.length} problème${state.health.problems.length > 1 ? "s" : ""})`,
      href: "/system",
      tone: "danger",
    });
  }
  for (const event of attention.security_events) {
    items.push({
      key: `secu-${event.kind}-${event.occurred_at}-${event.platform_user_id ?? ""}`,
      text: securityEventText(event),
      href: event.platform_user_id ? `/team?member=${event.platform_user_id}` : "/team",
      tone: securityEventTone(event),
    });
  }
  for (const invitation of attention.expiring_invitations) {
    items.push({
      key: `inv-${invitation.id}`,
      text: `L'invitation de ${invitation.display_name} expire le ${formatDateTime(invitation.expires_at)}`,
      href: "/team?status=invited",
      tone: "attention",
    });
  }
  for (const trial of attention.trials_ending) {
    items.push({
      key: `essai-${trial.company_id}`,
      text: `L'essai de ${trial.name} se termine le ${formatDate(trial.trial_ends_at)}`,
      href: `/companies/${trial.company_id}`,
      tone: "attention",
    });
  }
  for (const company of attention.suspended_companies) {
    items.push({
      key: `susp-${company.company_id}`,
      text: `${company.name} est suspendue`,
      href: `/companies/${company.company_id}`,
      tone: "danger",
    });
  }
  const hiddenSuspended = attention.suspended_total - attention.suspended_companies.length;

  return (
    <Card aria-labelledby="titre-a-traiter" className="space-y-3">
      <h2 id="titre-a-traiter" className="text-lg font-bold">
        À traiter
      </h2>
      {items.length === 0 ? (
        <p className="flex items-center gap-2 text-succes">
          <CheckCircle2 aria-hidden="true" className="size-5" />
          Rien à traiter pour l&apos;instant : aucune invitation ni aucun essai sur le point de
          finir, aucune entreprise suspendue, le système tourne.
        </p>
      ) : (
        <ul className="divide-y divide-trait">
          {items.map((item) => (
            <li key={item.key}>
              <Link
                href={item.href}
                className="flex min-h-11 items-center gap-3 py-2 hover:underline"
              >
                <span
                  aria-hidden="true"
                  className={`size-2.5 shrink-0 rounded-full ${item.tone === "danger" ? "bg-danger" : "bg-attention"}`}
                />
                {item.text}
              </Link>
            </li>
          ))}
          {hiddenSuspended > 0 && (
            <li>
              <Link
                href="/companies?status=suspended"
                className="flex min-h-11 items-center py-2 underline"
              >
                Et {hiddenSuspended} autre{hiddenSuspended > 1 ? "s" : ""} entreprise
                {hiddenSuspended > 1 ? "s" : ""} suspendue{hiddenSuspended > 1 ? "s" : ""}
              </Link>
            </li>
          )}
        </ul>
      )}
      <p className="text-sm text-encre-douce">
        Mis à jour le {formatDateTime(attention.computed_at)}
      </p>
    </Card>
  );
}

export function Dashboard() {
  const [team, setTeam] = useState<TeamSummary | null>(null);
  const [overview, setOverview] = useState<StatsOverview | null>(null);
  const [attention, setAttention] = useState<AttentionRead | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fail = (caught: unknown) => setError(errorMessage(caught));
    unwrap(api.GET("/api/v1/platform/team/summary")).then(setTeam, fail);
    unwrap(api.GET("/api/v1/platform/stats/overview")).then(setOverview, fail);
    unwrap(api.GET("/api/v1/platform/attention")).then(setAttention, fail);
  }, []);

  return (
    <section aria-labelledby="titre-tableau" className="space-y-8">
      <PageHeader id="titre-tableau" title="Tableau de bord" />
      {error && <Notice tone="danger">{error}</Notice>}
      {attention ? <ToHandle attention={attention} /> : <p aria-live="polite">Chargement…</p>}
      {team && (
        <Tiles
          title="Équipe"
          computedAt={team.computed_at}
          tiles={[
            { label: "Comptes", value: team.members, href: "/team" },
            { label: "Actifs", value: team.active, href: "/team?status=active" },
            { label: "Suspendus", value: team.suspended, href: "/team?status=suspended" },
            {
              label: "Invitations en attente",
              value: team.pending_invitations,
              href: "/team?status=invited",
            },
          ]}
        />
      )}
      {overview && (
        <Tiles
          title="Commerçants"
          computedAt={overview.computed_at}
          tiles={[
            {
              label: "Entreprises actives",
              value: overview.companies.active,
              href: "/companies?status=active",
            },
            {
              label: "En essai",
              value: overview.companies.trial,
              href: "/companies?status=trial",
            },
            {
              label: "Suspendues",
              value: overview.companies.suspended,
              href: "/companies?status=suspended",
            },
            {
              label: "Comptes commerçants actifs",
              value: overview.active_users,
              href: "/users?status=active",
            },
          ]}
        />
      )}
    </section>
  );
}
