"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useId, useState, type FormEvent } from "react";

import {
  BUTTON,
  Chip,
  EmptyState,
  FIELD,
  LABEL,
  Notice,
  PageHeader,
  Pager,
  Skeleton,
} from "@/components/ui";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { AuditEntry, AuditPage, TeamMember } from "@/lib/api/schema";
import { ACTION_LABELS, describeEntry } from "@/lib/audit";
import { formatDateTime } from "@/lib/format";
import { pageOf, withParams } from "@/lib/query";

export const PAGE_SIZE = 50;
type Action = AuditEntry["action"];

/** Journal des modifications de la plateforme (prompt 27, D4 d), administrateurs seuls. */
export function Journal() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const actorId = useId();
  const actionId = useId();
  const startId = useId();
  const endId = useId();
  const actor = params.get("actor") ?? "";
  const action = params.get("action") ?? "";
  const company = params.get("company") ?? "";
  const entity = params.get("entity") ?? "";
  const start = params.get("start") ?? "";
  const end = params.get("end") ?? "";
  const page = pageOf(params);
  const [startDraft, setStartDraft] = useState(start);
  const [endDraft, setEndDraft] = useState(end);
  const [data, setData] = useState<AuditPage | null>(null);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [error, setError] = useState<string | null>(null);
  const href = (changes: Record<string, string | null>) => withParams(pathname, params, changes);

  useEffect(() => {
    unwrap(api.GET("/api/v1/platform/team")).then(
      (team) => setMembers(team.members),
      () => undefined,
    );
  }, []);

  useEffect(() => {
    let alive = true;
    unwrap(
      api.GET("/api/v1/platform/audit", {
        params: {
          query: {
            actor_id: actor || undefined,
            action: (action || undefined) as Action | undefined,
            company_id: company || undefined,
            entity_id: entity || undefined,
            start: start || undefined,
            end: end || undefined,
            page,
            page_size: PAGE_SIZE,
          },
        },
      }),
    ).then(
      (result) => alive && (setData(result), setError(null)),
      (caught: unknown) => alive && (setData(null), setError(errorMessage(caught))),
    );
    return () => {
      alive = false;
    };
  }, [actor, action, company, entity, start, end, page]);

  function applyPeriod(event: FormEvent) {
    event.preventDefault();
    router.push(href({ start: startDraft || null, end: endDraft || null }));
  }

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const companyName =
    company && data?.items.find((item) => item.target_company_id === company)?.target_company_name;
  const entityName = entity && data?.items.find((item) => item.entity_id === entity)?.entity_name;

  return (
    <section aria-labelledby="titre-journal" className="space-y-5">
      <PageHeader
        id="titre-journal"
        title="Journal"
        description="Qui a fait quoi dans l'administration, le plus récent d'abord."
      />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="min-w-0 space-y-1">
          <label htmlFor={actorId} className={LABEL}>
            Qui
          </label>
          <select
            id={actorId}
            value={actor}
            onChange={(event) => router.push(href({ actor: event.target.value || null }))}
            className={FIELD}
          >
            <option value="">Tout le monde</option>
            {members.map((member) => (
              <option key={member.id} value={member.id}>
                {member.display_name}
              </option>
            ))}
          </select>
        </div>
        <div className="min-w-0 space-y-1">
          <label htmlFor={actionId} className={LABEL}>
            Quoi
          </label>
          <select
            id={actionId}
            value={action}
            onChange={(event) => router.push(href({ action: event.target.value || null }))}
            className={FIELD}
          >
            <option value="">Tous les gestes</option>
            {Object.entries(ACTION_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <form
          onSubmit={applyPeriod}
          className="flex min-w-0 flex-wrap items-end gap-2 sm:col-span-2"
        >
          <div className="min-w-0 flex-1 space-y-1">
            <label htmlFor={startId} className={LABEL}>
              Du
            </label>
            <input
              id={startId}
              type="date"
              value={startDraft}
              onChange={(e) => setStartDraft(e.target.value)}
              className={FIELD}
            />
          </div>
          <div className="min-w-0 flex-1 space-y-1">
            <label htmlFor={endId} className={LABEL}>
              Au
            </label>
            <input
              id={endId}
              type="date"
              value={endDraft}
              onChange={(e) => setEndDraft(e.target.value)}
              className={FIELD}
            />
          </div>
          <button type="submit" className={BUTTON.secondary}>
            Filtrer
          </button>
        </form>
      </div>
      {(company || entity) && (
        <div className="flex flex-wrap gap-2" role="group" aria-label="Filtres actifs">
          {company && (
            <Chip href={href({ company: null })} active>
              Entreprise : {companyName || "choisie"} ×
              <span className="sr-only"> (retirer ce filtre)</span>
            </Chip>
          )}
          {entity && (
            <Chip href={href({ entity: null })} active>
              Sur : {entityName || "un compte"} ×
              <span className="sr-only"> (retirer ce filtre)</span>
            </Chip>
          )}
        </div>
      )}

      {error && <Notice tone="danger">{error}</Notice>}
      {!data && !error && <Skeleton label="Chargement du journal" />}
      {data && data.items.length === 0 && (
        <EmptyState title="Rien dans le journal pour ces filtres.">
          <Link href={pathname} className="underline">
            Tout afficher
          </Link>
        </EmptyState>
      )}
      {data && data.items.length > 0 && (
        <>
          <p className="text-encre-douce" aria-live="polite">
            {data.total} ligne{data.total > 1 ? "s" : ""}
          </p>
          <ol className="divide-y divide-trait rounded-xl border border-trait bg-surface">
            {data.items.map((entry) => (
              <li
                key={entry.id}
                className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-baseline sm:gap-4"
              >
                <time
                  dateTime={entry.occurred_at}
                  className="shrink-0 text-sm text-encre-douce sm:w-40"
                >
                  {formatDateTime(entry.occurred_at)}
                </time>
                <p className="min-w-0 flex-1">{describeEntry(entry)}</p>
                {entry.target_company_id && (
                  <Link
                    href={`/companies/${entry.target_company_id}`}
                    className="shrink-0 text-sm font-semibold underline"
                  >
                    Voir l&apos;entreprise
                    <span className="sr-only"> {entry.target_company_name}</span>
                  </Link>
                )}
              </li>
            ))}
          </ol>
          <Pager page={page} pages={pages} href={(next) => href({ page: String(next) })} />
        </>
      )}
    </section>
  );
}
