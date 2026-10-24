"use client";

import { useCallback, useEffect, useId, useState, type FormEvent } from "react";

import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { SupportSessionList, SupportSessionRead } from "@/lib/api/schema";
import { formatDateTime, formatRemaining } from "@/lib/format";

/** Durées proposées, en minutes : 2 h par défaut, 4 h au plus (la base le vérifie aussi). */
export const DURATIONS = [
  { minutes: 30, label: "30 minutes" },
  { minutes: 60, label: "1 heure" },
  { minutes: 120, label: "2 heures" },
  { minutes: 180, label: "3 heures" },
  { minutes: 240, label: "4 heures (maximum)" },
] as const;

const MIN_REASON = 10;

/**
 * Ouvre l'application commerçante dans un nouvel onglet, le jeton dans le **fragment** :
 * il n'est envoyé à aucun serveur, et la page d'entrée l'efface aussitôt de l'adresse.
 * L'onglet est ouvert avant d'attendre le jeton (sinon le navigateur le bloque), puis
 * détaché de cette fenêtre (`opener` à `null`).
 */
export async function openMerchantTab(
  merchantUrl: string,
  fetchToken: () => Promise<{ access_token: string; expires_in: number }>,
  open: (url: string) => Window | null = (url) => window.open(url, "_blank"),
): Promise<void> {
  const tab = open("about:blank");
  if (tab) tab.opener = null;
  try {
    const { access_token, expires_in } = await fetchToken();
    const fragment = new URLSearchParams({ token: access_token, expires_in: String(expires_in) });
    const target = `${merchantUrl.replace(/\/+$/, "")}/support#${fragment.toString()}`;
    if (tab) tab.location.href = target;
  } catch (caught) {
    tab?.close();
    throw caught;
  }
}

/**
 * Accès support encadré (ADR 0092), sur la fiche d'une entreprise : bris de glace avec
 * justification obligatoire et durée bornée, compte à rebours, « Voir l'entreprise »,
 * « Fermer l'accès », et les dernières sessions. L'entreprise le voit dans un bandeau et
 * dans son journal ; le gérant est prévenu.
 */
export function SupportAccessCard({
  companyId,
  suspended,
  merchantUrl,
}: {
  companyId: string;
  suspended: boolean;
  merchantUrl: string;
}) {
  const reasonId = useId();
  const durationId = useId();
  const [sessions, setSessions] = useState<SupportSessionList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [minutes, setMinutes] = useState(120);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  const reload = useCallback(
    () =>
      unwrap(
        api.GET("/api/v1/platform/companies/{company_id}/support-sessions", {
          params: { path: { company_id: companyId } },
        }),
      ).then(setSessions, (caught: unknown) => setError(errorMessage(caught))),
    [companyId],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  // Compte à rebours relu toutes les 30 s ; à l'heure dite, la liste est relue.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);
  const active = sessions?.active ?? null;
  const expired = active !== null && Date.parse(active.expires_at) <= now;
  useEffect(() => {
    if (expired) void reload();
  }, [expired, reload]);

  if (error) {
    return (
      <p role="alert" className="rounded bg-danger-teinte px-3 py-2 text-danger">
        {error}
      </p>
    );
  }
  if (!sessions) return <p aria-live="polite">Chargement de l&apos;accès support…</p>;

  async function open(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (reason.trim().length < MIN_REASON) {
      setFormError("Expliquez en quelques mots pourquoi l'accès est nécessaire.");
      return;
    }
    setBusy(true);
    try {
      await unwrap(
        api.POST("/api/v1/platform/companies/{company_id}/support-sessions", {
          params: { path: { company_id: companyId } },
          body: { justification: reason.trim(), duration_minutes: minutes },
        }),
      );
      setReason("");
      setFormError(null);
      setNotice("Accès support ouvert. Le gérant est prévenu.");
      setNow(Date.now());
      await reload();
    } catch (caught) {
      setFormError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function view(session: SupportSessionRead) {
    setFormError(null);
    try {
      await openMerchantTab(merchantUrl, () =>
        unwrap(
          api.POST("/api/v1/platform/support-sessions/{session_id}/token", {
            params: { path: { session_id: session.id } },
          }),
        ),
      );
    } catch (caught) {
      setFormError(errorMessage(caught));
    }
  }

  async function close(session: SupportSessionRead) {
    setBusy(true);
    try {
      await unwrap(
        api.DELETE("/api/v1/platform/support-sessions/{session_id}", {
          params: { path: { session_id: session.id } },
        }),
      );
      setNotice("Accès support fermé.");
      await reload();
    } catch (caught) {
      setFormError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  const live = active && !expired ? active : null;
  return (
    <section
      aria-labelledby="titre-support"
      className="space-y-4 rounded border border-trait bg-surface p-4"
    >
      <h2 id="titre-support" className="text-xl font-bold">
        Accès support
      </h2>
      <p className="text-encre-douce">
        Lecture seule des données de l&apos;entreprise, pour une durée limitée. Le gérant est
        prévenu, un bandeau l&apos;indique à tous ses utilisateurs, et les deux journaux en gardent
        la trace.
      </p>
      {notice && (
        <p role="status" className="rounded bg-succes-teinte px-3 py-2 text-succes">
          {notice}
        </p>
      )}

      {live ? (
        <div className="space-y-3 rounded bg-attention-teinte p-3">
          <p className="font-semibold text-attention">
            Accès ouvert par {live.opened_by_me ? "vous" : live.opened_by} jusqu&apos;à{" "}
            {formatDateTime(live.expires_at)} — {formatRemaining(live.expires_at, now)}
          </p>
          {live.justification && <p>Motif : {live.justification}</p>}
          <div className="flex flex-wrap gap-3">
            {live.opened_by_me && (
              <button
                type="button"
                onClick={() => void view(live)}
                className="rounded bg-accent px-4 py-2 font-semibold text-accent-encre"
              >
                Voir l&apos;entreprise
              </button>
            )}
            <button
              type="button"
              disabled={busy}
              onClick={() => void close(live)}
              className="rounded border border-trait bg-surface px-4 py-2 font-semibold"
            >
              Fermer l&apos;accès
            </button>
          </div>
        </div>
      ) : suspended ? (
        <p className="text-encre-douce">
          L&apos;entreprise est suspendue : un accès support serait refusé.
        </p>
      ) : (
        <form onSubmit={open} className="space-y-3" aria-labelledby="titre-ouvrir-support">
          <h3 id="titre-ouvrir-support" className="font-bold">
            Ouvrir un accès support
          </h3>
          <div className="space-y-1">
            <label htmlFor={reasonId} className="block font-semibold">
              Pourquoi cet accès ?
            </label>
            <textarea
              id={reasonId}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              maxLength={1000}
              className="w-full rounded border border-trait bg-surface px-3 py-2"
            />
          </div>
          <div className="space-y-1">
            <label htmlFor={durationId} className="block font-semibold">
              Durée
            </label>
            <select
              id={durationId}
              value={minutes}
              onChange={(event) => setMinutes(Number(event.target.value))}
              className="w-full rounded border border-trait bg-surface px-3 py-2"
            >
              {DURATIONS.map((duration) => (
                <option key={duration.minutes} value={duration.minutes}>
                  {duration.label}
                </option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            disabled={busy}
            className="rounded bg-danger px-4 py-2 font-semibold text-surface"
          >
            Ouvrir un accès support
          </button>
        </form>
      )}
      {formError && (
        <p role="alert" className="rounded bg-danger-teinte px-3 py-2 text-danger">
          {formError}
        </p>
      )}

      {sessions.recent.length > 0 && (
        <div className="space-y-2">
          <h3 className="font-bold">Dernières sessions</h3>
          <ul className="space-y-2">
            {sessions.recent.map((session) => (
              <li key={session.id} className="rounded border border-trait px-3 py-2">
                <span className="font-semibold">{formatDateTime(session.started_at)}</span> ·{" "}
                {session.opened_by}
                {" · "}
                {session.ended_at
                  ? `terminée le ${formatDateTime(session.ended_at)}`
                  : session.is_open
                    ? "en cours"
                    : `échue le ${formatDateTime(session.expires_at)}`}
                {session.justification && (
                  <p className="text-sm text-encre-douce">{session.justification}</p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
