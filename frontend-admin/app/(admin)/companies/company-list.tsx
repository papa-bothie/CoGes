"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useId, useState } from "react";

import { StatusBadge } from "@/components/status-badge";
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
import type { CompanyPage, CompanySummary } from "@/lib/api/schema";
import { formatDate, formatDateTime } from "@/lib/format";
import { pageOf, withParams } from "@/lib/query";

const PAGE_SIZE = 20;
const STATUSES = [
  { value: "", label: "Toutes" },
  { value: "trial", label: "En essai" },
  { value: "active", label: "Actives" },
  { value: "suspended", label: "Suspendues" },
];

export function CompanyList() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const searchId = useId();
  const query = params.get("q") ?? "";
  const status = params.get("status") ?? "";
  const page = pageOf(params);
  const [search, setSearch] = useState(query);
  const [data, setData] = useState<CompanyPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const href = (changes: Record<string, string | null>) => withParams(pathname, params, changes);

  useEffect(() => {
    let alive = true;
    unwrap(
      api.GET("/api/v1/platform/companies", {
        params: {
          query: {
            page,
            page_size: PAGE_SIZE,
            search: query || undefined,
            status: (status || undefined) as CompanySummary["status"] | undefined,
          },
        },
      }),
    ).then(
      (result) => alive && (setData(result), setError(null)),
      (caught: unknown) => alive && setError(errorMessage(caught)),
    );
    return () => {
      alive = false;
    };
  }, [page, query, status]);

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <section aria-labelledby="titre-entreprises" className="space-y-5">
      <PageHeader
        id="titre-entreprises"
        title="Entreprises"
        description="Les commerçants inscrits : statut, comptes, dernière activité. Aucune donnée commerciale."
      />
      <form
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          router.push(href({ q: search.trim() || null }));
        }}
        className="flex max-w-xl flex-wrap items-end gap-2"
      >
        <div className="min-w-0 flex-1 space-y-1">
          <label htmlFor={searchId} className={LABEL}>
            Nom ou code
          </label>
          <input
            id={searchId}
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className={FIELD}
          />
        </div>
        <button type="submit" className={BUTTON.primary}>
          Chercher
        </button>
      </form>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Statut">
        {STATUSES.map((option) => (
          <Chip
            key={option.label}
            href={href({ status: option.value || null })}
            active={status === option.value}
          >
            {option.label}
          </Chip>
        ))}
      </div>

      {error && <Notice tone="danger">{error}</Notice>}
      {!data && !error && <Skeleton label="Chargement des entreprises" />}

      {data && (
        <>
          <p className="text-encre-douce" aria-live="polite">
            {data.total} entreprise{data.total > 1 ? "s" : ""}
          </p>
          {data.items.length === 0 ? (
            <EmptyState title="Aucune entreprise ne correspond.">
              Essayez un autre nom ou{" "}
              <Link href={pathname} className="underline">
                retirez les filtres
              </Link>
              .
            </EmptyState>
          ) : (
            <>
              <div className="hidden overflow-x-auto rounded-xl border border-trait bg-surface md:block">
                <table className="w-full text-left">
                  <thead className="border-b border-trait text-sm text-encre-douce">
                    <tr>
                      <th scope="col" className="px-4 py-3">
                        Entreprise
                      </th>
                      <th scope="col" className="px-4 py-3">
                        Statut
                      </th>
                      <th scope="col" className="px-4 py-3">
                        Inscription
                      </th>
                      <th scope="col" className="px-4 py-3">
                        Comptes
                      </th>
                      <th scope="col" className="px-4 py-3">
                        Dernière activité
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((company) => (
                      <tr key={company.id} className="border-b border-trait last:border-0">
                        <td className="px-4 py-3">
                          <Link
                            href={`/companies/${company.id}`}
                            className="font-semibold underline"
                          >
                            {company.name}
                          </Link>
                          <span className="block text-sm text-encre-douce">{company.slug}</span>
                        </td>
                        <td className="px-4 py-3">
                          <StatusBadge status={company.status} />
                        </td>
                        <td className="px-4 py-3">{formatDate(company.created_at)}</td>
                        <td className="px-4 py-3">{company.user_count}</td>
                        <td className="px-4 py-3">{formatDateTime(company.last_activity_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <ul aria-label="Entreprises" className="space-y-3 md:hidden">
                {data.items.map((company) => (
                  <li key={company.id} className="rounded-xl border border-trait bg-surface p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <Link href={`/companies/${company.id}`} className="font-semibold underline">
                          {company.name}
                        </Link>
                        <p className="text-sm text-encre-douce">{company.slug}</p>
                      </div>
                      <StatusBadge status={company.status} />
                    </div>
                    <p className="mt-2 text-sm text-encre-douce">
                      {company.user_count} compte{company.user_count > 1 ? "s" : ""} · inscrite le{" "}
                      {formatDate(company.created_at)}
                    </p>
                  </li>
                ))}
              </ul>
            </>
          )}
          <Pager page={page} pages={pages} href={(next) => href({ page: String(next) })} />
        </>
      )}
    </section>
  );
}
