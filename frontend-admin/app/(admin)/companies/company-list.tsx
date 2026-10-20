"use client";

import Link from "next/link";
import { useEffect, useId, useState } from "react";

import { StatusBadge } from "@/components/status-badge";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { CompanyPage } from "@/lib/api/schema";
import { formatDate, formatDateTime } from "@/lib/format";

const PAGE_SIZE = 20;

export function CompanyList() {
  const searchId = useId();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<CompanyPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    unwrap(
      api.GET("/api/v1/platform/companies", {
        params: { query: { page, page_size: PAGE_SIZE, search: query || undefined } },
      }),
    ).then(
      (result) => alive && (setData(result), setError(null)),
      (caught: unknown) => alive && setError(errorMessage(caught)),
    );
    return () => {
      alive = false;
    };
  }, [page, query]);

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <section aria-labelledby="titre-entreprises" className="space-y-4">
      <h1 id="titre-entreprises" className="text-2xl font-bold">
        Entreprises
      </h1>
      <form
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          setPage(1);
          setQuery(search.trim());
        }}
        className="flex flex-wrap items-end gap-2"
      >
        <div className="min-w-0 flex-1 space-y-1">
          <label htmlFor={searchId} className="block font-semibold">
            Nom ou code
          </label>
          <input
            id={searchId}
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="w-full rounded border border-trait bg-surface px-3 py-2"
          />
        </div>
        <button
          type="submit"
          className="rounded bg-accent px-4 py-2 font-semibold text-accent-encre"
        >
          Chercher
        </button>
      </form>

      {error && (
        <p role="alert" className="rounded bg-danger-teinte px-3 py-2 text-danger">
          {error}
        </p>
      )}

      {data && (
        <>
          <p className="text-encre-douce" aria-live="polite">
            {data.total} entreprise{data.total > 1 ? "s" : ""}
          </p>
          <div className="overflow-x-auto rounded border border-trait bg-surface">
            <table className="w-full text-left">
              <thead className="border-b border-trait text-sm text-encre-douce">
                <tr>
                  <th scope="col" className="px-3 py-2">
                    Entreprise
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Statut
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Inscription
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Comptes
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Dernière activité
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((company) => (
                  <tr key={company.id} className="border-b border-trait last:border-0">
                    <td className="px-3 py-2">
                      <Link href={`/companies/${company.id}`} className="font-semibold underline">
                        {company.name}
                      </Link>
                      <span className="block text-sm text-encre-douce">{company.slug}</span>
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge status={company.status} />
                    </td>
                    <td className="px-3 py-2">{formatDate(company.created_at)}</td>
                    <td className="px-3 py-2">{company.user_count}</td>
                    <td className="px-3 py-2">{formatDateTime(company.last_activity_at)}</td>
                  </tr>
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
