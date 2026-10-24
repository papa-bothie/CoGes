"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useSystemHealth } from "@/components/system-health";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { PlatformOutbox, WorkersHealth } from "@/lib/api/schema";
import { formatAge, formatDateTime, formatTime } from "@/lib/format";
import { COMPONENT_LABELS, JOB_STATE_LABELS, jobLabel } from "@/lib/system";

/** Pastille et mot : jamais la couleur seule. */
export function Light({ healthy, label }: { healthy: boolean; label?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-2 font-semibold ${healthy ? "text-succes" : "text-danger"}`}
    >
      <span
        aria-hidden="true"
        className={`inline-block size-2.5 rounded-full ${healthy ? "bg-succes" : "bg-danger"}`}
      />
      {label ?? (healthy ? "En marche" : "En panne")}
    </span>
  );
}

export function SystemOverview() {
  const { state, refresh } = useSystemHealth();
  const [outbox, setOutbox] = useState<PlatformOutbox | null>(null);
  const [outboxError, setOutboxError] = useState<string | null>(null);
  const checkedAt = state.kind === "ok" || state.kind === "down" ? state.health.checked_at : null;

  // Le rebut suit le même rythme que le bilan : relu à chaque bilan reçu.
  useEffect(() => {
    let alive = true;
    unwrap(
      api.GET("/api/v1/platform/system/outbox", { params: { query: { page_size: 50 } } }),
    ).then(
      (result) => alive && (setOutbox(result), setOutboxError(null)),
      (caught: unknown) => alive && setOutboxError(errorMessage(caught)),
    );
    return () => {
      alive = false;
    };
  }, [checkedAt]);

  return (
    <section aria-labelledby="titre-systeme" className="space-y-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 id="titre-systeme" className="text-2xl font-bold">
          Système
        </h1>
        <p className="text-encre-douce">
          {checkedAt ? `Vérifié à ${formatTime(checkedAt)}, toutes les 30 s` : "Vérification…"}{" "}
          <button
            type="button"
            onClick={() => void refresh()}
            className="ml-2 rounded border border-trait px-3 py-1.5 text-sm font-semibold text-encre"
          >
            Actualiser
          </button>
        </p>
      </div>

      {state.kind === "unknown" && (
        <p className="rounded bg-attention-teinte px-3 py-2 text-attention">{state.message}</p>
      )}
      {(state.kind === "ok" || state.kind === "down") && <Health health={state.health} />}

      <section aria-labelledby="titre-rebut" className="space-y-2">
        <h2 id="titre-rebut" className="text-lg font-bold">
          Événements au rebut
        </h2>
        {outboxError && <p className="text-danger">{outboxError}</p>}
        {outbox && outbox.dead_letters.total === 0 && (
          <p className="text-encre-douce">Aucun événement au rebut.</p>
        )}
        {outbox && outbox.dead_letters.total > 0 && (
          <>
            <p>
              À rejouer à la main, après avoir corrigé la cause (guide des workers). Seuls
              l&apos;identifiant, le type, la date et les tentatives sont montrés.
            </p>
            <div className="overflow-x-auto rounded border border-trait bg-surface">
              <table className="w-full text-left">
                <thead className="border-b border-trait text-sm text-encre-douce">
                  <tr>
                    <th scope="col" className="px-3 py-2">
                      Identifiant
                    </th>
                    <th scope="col" className="px-3 py-2">
                      Type
                    </th>
                    <th scope="col" className="px-3 py-2">
                      Date
                    </th>
                    <th scope="col" className="px-3 py-2">
                      Tentatives
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {outbox.dead_letters.items.map((event) => (
                    <tr key={event.id} className="border-b border-trait last:border-0">
                      <td className="px-3 py-2 font-mono">{event.id}</td>
                      <td className="px-3 py-2 font-mono">{event.event_type}</td>
                      <td className="px-3 py-2">{formatDateTime(event.occurred_at)}</td>
                      <td className="px-3 py-2">{event.attempts}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {outbox.dead_letters.total > outbox.dead_letters.items.length && (
              <p className="text-encre-douce">
                {outbox.dead_letters.items.length} premiers sur {outbox.dead_letters.total}.
              </p>
            )}
          </>
        )}
      </section>
    </section>
  );
}

function Health({ health }: { health: WorkersHealth }) {
  const tickOk =
    health.beat_tick_age_seconds !== null && !health.problems.includes("beat_tick_missing");
  return (
    <>
      <p className="text-lg">
        <Light
          healthy={health.healthy}
          label={health.healthy ? "Tout fonctionne" : "Au moins un problème"}
        />
      </p>

      <section aria-labelledby="titre-composants" className="space-y-2">
        <h2 id="titre-composants" className="text-lg font-bold">
          Processus
        </h2>
        <ul className="grid gap-3 sm:grid-cols-3">
          {health.components.map((component) => {
            const youngest = Math.min(...component.hosts.map((host) => host.age_seconds));
            return (
              <li key={component.component} className="rounded border border-trait bg-surface p-3">
                <p className="font-semibold">
                  {COMPONENT_LABELS[component.component] ?? component.component}
                </p>
                <Light healthy={component.healthy} />
                <p className="text-sm text-encre-douce">
                  {component.hosts.length
                    ? `Dernier battement il y a ${formatAge(youngest)}`
                    : "Aucun battement reçu"}
                </p>
              </li>
            );
          })}
        </ul>
      </section>

      <section aria-labelledby="titre-files" className="space-y-2">
        <h2 id="titre-files" className="text-lg font-bold">
          Files d&apos;attente
        </h2>
        <dl className="grid gap-3 sm:grid-cols-3">
          <div className="rounded border border-trait bg-surface p-3">
            <dt className="font-semibold">Tic du planificateur</dt>
            <dd>
              <Light healthy={tickOk} />
              <span className="block text-sm text-encre-douce">
                {health.beat_tick_age_seconds === null
                  ? "Jamais reçu"
                  : `Il y a ${formatAge(health.beat_tick_age_seconds)}`}
              </span>
            </dd>
          </div>
          <div className="rounded border border-trait bg-surface p-3">
            <dt className="font-semibold">Tâches en attente</dt>
            <dd>{health.queue.length === null ? "Illisible (Redis)" : health.queue.length}</dd>
          </div>
          {health.outbox && (
            <div className="rounded border border-trait bg-surface p-3">
              <dt className="font-semibold">Événements à publier</dt>
              <dd>
                <Light
                  healthy={health.outbox.healthy}
                  label={`${health.outbox.pending} en attente`}
                />
                <span className="block text-sm text-encre-douce">
                  Plus ancien : {formatAge(health.outbox.lag_seconds)} (seuil{" "}
                  {formatAge(health.outbox.max_lag_seconds)}) · {health.outbox.dead_lettered} au
                  rebut
                </span>
              </dd>
            </div>
          )}
        </dl>
      </section>

      <section aria-labelledby="titre-taches" className="space-y-2">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="titre-taches" className="text-lg font-bold">
            Tâches planifiées
          </h2>
          <Link href="/system/jobs" className="font-semibold underline">
            Historique des tâches
          </Link>
        </div>
        <div className="overflow-x-auto rounded border border-trait bg-surface">
          <table className="w-full text-left">
            <thead className="border-b border-trait text-sm text-encre-douce">
              <tr>
                <th scope="col" className="px-3 py-2">
                  Tâche
                </th>
                <th scope="col" className="px-3 py-2">
                  État
                </th>
                <th scope="col" className="px-3 py-2">
                  Dernière réussite
                </th>
                <th scope="col" className="px-3 py-2">
                  Entreprises
                </th>
              </tr>
            </thead>
            <tbody>
              {health.jobs.map((job) => (
                <tr key={job.job} className="border-b border-trait last:border-0">
                  <td className="px-3 py-2">
                    {jobLabel(job.job)}
                    <span className="block font-mono text-sm text-encre-douce">{job.job}</span>
                  </td>
                  <td className="px-3 py-2">
                    <Light healthy={job.healthy} label={JOB_STATE_LABELS[job.state] ?? job.state} />
                    <span className="block text-sm text-encre-douce">
                      Fenêtre de {job.window_hours} h
                    </span>
                  </td>
                  <td className="px-3 py-2">{formatDateTime(job.last_ok_at)}</td>
                  <td className="px-3 py-2">
                    {job.companies_ok + job.companies_failed === 0
                      ? "—"
                      : `${job.companies_ok} réussie(s), ${job.companies_failed} en échec`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
