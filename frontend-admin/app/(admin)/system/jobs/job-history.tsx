"use client";

import { Fragment, useEffect, useId, useState } from "react";

import { useSystemHealth } from "@/components/system-health";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { JobRun, JobRunPage } from "@/lib/api/schema";
import { formatAge, formatDateTime } from "@/lib/format";
import { RUN_STATUS_LABELS, jobLabel } from "@/lib/system";

const PAGE_SIZE = 50;
type Status = "ok" | "failed" | "running";

const STATUS_FILTERS: { value: Status | ""; label: string }[] = [
  { value: "", label: "Tous les statuts" },
  { value: "failed", label: "En échec" },
  { value: "ok", label: "Réussies" },
  { value: "running", label: "En cours" },
];

const TONES: Record<string, string> = {
  ok: "bg-succes-teinte text-succes",
  failed: "bg-danger-teinte text-danger",
  running: "bg-attention-teinte text-attention",
};

export function JobHistory() {
  const statusId = useId();
  const jobId = useId();
  const { state } = useSystemHealth();
  const [status, setStatus] = useState<Status | "">("");
  const [job, setJob] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<JobRunPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [opened, setOpened] = useState<number | null>(null);

  // Les tâches du filtre : celles que le bilan connaît (`beat.py`).
  const jobs =
    state.kind === "ok" || state.kind === "down" ? state.health.jobs.map((j) => j.job) : [];

  useEffect(() => {
    let alive = true;
    unwrap(
      api.GET("/api/v1/platform/system/job-runs", {
        params: {
          query: { page, page_size: PAGE_SIZE, status: status || undefined, job: job || undefined },
        },
      }),
    ).then(
      (result) => alive && (setData(result), setError(null)),
      (caught: unknown) => alive && setError(errorMessage(caught)),
    );
    return () => {
      alive = false;
    };
  }, [page, status, job]);

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const toggle = (id: number) => setOpened((current) => (current === id ? null : id));

  return (
    <section aria-labelledby="titre-historique" className="space-y-4">
      <h1 id="titre-historique" className="text-2xl font-bold">
        Historique des tâches
      </h1>
      <p className="text-encre-douce">
        Les 90 derniers jours, la plus récente d&apos;abord. Une tâche restée « en cours » au-delà
        de son délai compte comme un échec.
      </p>

      <div className="flex flex-wrap gap-4">
        <div className="space-y-1">
          <label htmlFor={statusId} className="block font-semibold">
            Statut
          </label>
          <select
            id={statusId}
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as Status | "");
              setPage(1);
            }}
            className="rounded border border-trait bg-surface px-3 py-2"
          >
            {STATUS_FILTERS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <label htmlFor={jobId} className="block font-semibold">
            Tâche
          </label>
          <select
            id={jobId}
            value={job}
            onChange={(event) => {
              setJob(event.target.value);
              setPage(1);
            }}
            className="rounded border border-trait bg-surface px-3 py-2"
          >
            <option value="">Toutes les tâches</option>
            {jobs.map((name) => (
              <option key={name} value={name}>
                {jobLabel(name)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <p role="alert" className="rounded bg-danger-teinte px-3 py-2 text-danger">
          {error}
        </p>
      )}

      {data && (
        <>
          <p className="text-encre-douce" aria-live="polite">
            {data.total} exécution{data.total > 1 ? "s" : ""}
          </p>
          <div className="overflow-x-auto rounded border border-trait bg-surface">
            <table className="w-full text-left">
              <thead className="border-b border-trait text-sm text-encre-douce">
                <tr>
                  <th scope="col" className="px-3 py-2">
                    Début
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Tâche
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Statut
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Durée
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Portée
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((run) => (
                  <Fragment key={run.id}>
                    <tr
                      className={`border-b border-trait last:border-0 ${run.status === "failed" ? "cursor-pointer" : ""}`}
                      onClick={() => run.status === "failed" && toggle(run.id)}
                    >
                      <td className="px-3 py-2">{formatDateTime(run.started_at)}</td>
                      <td className="px-3 py-2">
                        {jobLabel(run.job)}
                        <span className="block font-mono text-sm text-encre-douce">{run.job}</span>
                      </td>
                      <td className="px-3 py-2">
                        <RunStatus
                          run={run}
                          opened={opened === run.id}
                          onToggle={() => toggle(run.id)}
                        />
                      </td>
                      <td className="px-3 py-2">{duration(run)}</td>
                      <td className="px-3 py-2">
                        {run.per_company ? "Une entreprise" : "Plateforme"}
                      </td>
                    </tr>
                    {opened === run.id && (
                      <tr className="border-b border-trait bg-danger-teinte">
                        <td colSpan={5} id={`erreur-${run.id}`} className="px-3 py-2 text-danger">
                          {run.error ? (
                            <>
                              Erreur : <code className="font-mono">{run.error}</code>
                            </>
                          ) : (
                            "Aucun message enregistré : l'exécution a été interrompue (worker arrêté ou délai dépassé)."
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          {pages > 1 && (
            <nav aria-label="Pages" className="flex items-center gap-3">
              <button
                type="button"
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
                className="rounded border border-trait px-3 py-1.5 disabled:opacity-50"
              >
                Précédente
              </button>
              <span>
                Page {page} sur {pages}
              </span>
              <button
                type="button"
                disabled={page >= pages}
                onClick={() => setPage(page + 1)}
                className="rounded border border-trait px-3 py-1.5 disabled:opacity-50"
              >
                Suivante
              </button>
            </nav>
          )}
        </>
      )}
    </section>
  );
}

function RunStatus({
  run,
  opened,
  onToggle,
}: {
  run: JobRun;
  opened: boolean;
  onToggle: () => void;
}) {
  const badge = (
    <span className={`rounded px-2 py-0.5 text-sm font-semibold ${TONES[run.status] ?? ""}`}>
      {RUN_STATUS_LABELS[run.status] ?? run.status}
    </span>
  );
  if (run.status !== "failed") return badge;
  // Le clic sur la ligne ouvre le détail ; le bouton le rend accessible au clavier.
  return (
    <button
      type="button"
      aria-expanded={opened}
      aria-controls={opened ? `erreur-${run.id}` : undefined}
      onClick={(event) => {
        event.stopPropagation();
        onToggle();
      }}
      className="inline-flex items-center gap-2"
    >
      {badge}
      <span className="text-sm underline">{opened ? "Masquer l'erreur" : "Voir l'erreur"}</span>
    </button>
  );
}

function duration(run: JobRun): string {
  if (!run.finished_at) return "—";
  const seconds = (Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000;
  return formatAge(Math.max(0, seconds));
}
