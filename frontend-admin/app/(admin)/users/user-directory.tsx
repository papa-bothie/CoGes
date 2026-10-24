"use client";

import { ArrowDown, ArrowUp, Building2, Lock } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useId, useState } from "react";

import {
  Chip,
  EmptyState,
  FIELD,
  Notice,
  PageHeader,
  Pager,
  Pill,
  Skeleton,
} from "@/components/ui";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { MerchantUser, MerchantUserPage } from "@/lib/api/schema";
import { MERCHANT_STATUS_LABELS, ROLE_LABELS, formatDateTime, formatRelative } from "@/lib/format";
import { pageOf, withParams } from "@/lib/query";

export const PAGE_SIZE = 20;
export const TYPING_DELAY_MS = 300;

const ROLES = [
  { value: "", label: "Tous les rôles" },
  { value: "gerant", label: "Gérant" },
  { value: "vendeur", label: "Vendeur" },
  { value: "comptable", label: "Comptable" },
];
const STATUSES = [
  { value: "", label: "Tous" },
  { value: "active", label: "Actifs" },
  { value: "deactivated", label: "Désactivés" },
  { value: "company_suspended", label: "Entreprise suspendue" },
];
type Sort = "name" | "-name" | "last_login" | "-last_login";

const STATUS_TONES: Record<string, "succes" | "neutre" | "danger"> = {
  active: "succes",
  deactivated: "neutre",
  company_suspended: "danger",
};

function LastLogin({ value }: { value: string | null }) {
  if (!value) return <span className="text-encre-douce">Jamais</span>;
  const exact = formatDateTime(value);
  return (
    <time dateTime={value} title={exact}>
      {formatRelative(value)}
      <span className="sr-only"> (le {exact})</span>
    </time>
  );
}

function roles(user: MerchantUser): string {
  return user.roles.map((role) => ROLE_LABELS[role] ?? role).join(", ") || "—";
}

export function UserDirectory() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const searchId = useId();
  const q = params.get("q") ?? "";
  const role = params.get("role") ?? "";
  const status = params.get("status") ?? "";
  const company = params.get("company") ?? "";
  const sort = (params.get("sort") as Sort | null) ?? "-last_login";
  const page = pageOf(params);

  const [typed, setTyped] = useState(q);
  const [data, setData] = useState<MerchantUserPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const href = (changes: Record<string, string | null>) => withParams(pathname, params, changes);

  // Saisie différée : l'adresse (donc la requête) suit la frappe après 300 ms.
  useEffect(() => {
    if (typed === q) return;
    const timer = window.setTimeout(
      () => router.replace(href({ q: typed.trim() || null })),
      TYPING_DELAY_MS,
    );
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typed]);

  useEffect(() => {
    let alive = true;
    unwrap(
      api.GET("/api/v1/platform/users", {
        params: {
          query: {
            q: q || undefined,
            role: role || undefined,
            status: (status || undefined) as MerchantUser["status"] | undefined,
            company_id: company || undefined,
            sort,
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
  }, [q, role, status, company, sort, page]);

  const loading = data === null && error === null;
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const companyName = company && data?.items[0]?.company_name;
  const filtered = Boolean(q || role || status || company);

  function sortHeader(label: string, key: "name" | "last_login") {
    const ascending = sort === key;
    const descending = sort === `-${key}`;
    const next = ascending ? `-${key}` : descending ? key : key === "name" ? "name" : "-last_login";
    return (
      <th
        scope="col"
        aria-sort={ascending ? "ascending" : descending ? "descending" : "none"}
        className="px-4 py-3"
      >
        <Link
          href={href({ sort: next })}
          className="inline-flex items-center gap-1 hover:underline"
        >
          {label}
          {ascending && <ArrowUp aria-hidden="true" className="size-4" />}
          {descending && <ArrowDown aria-hidden="true" className="size-4" />}
        </Link>
      </th>
    );
  }

  return (
    <section aria-labelledby="titre-utilisateurs" className="space-y-5">
      <PageHeader
        id="titre-utilisateurs"
        title="Utilisateurs"
        description="Les comptes des commerçants, toutes entreprises confondues."
      />
      <p className="flex items-center gap-2 rounded-lg bg-voile px-4 py-3">
        <Lock aria-hidden="true" className="size-4 shrink-0" />
        Lecture seule — les comptes des commerçants sont gérés par leur gérant.
      </p>

      <div className="space-y-3">
        <div className="max-w-md space-y-1">
          <label htmlFor={searchId} className="block font-semibold">
            Nom, e-mail ou entreprise
          </label>
          <input
            id={searchId}
            type="search"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            className={FIELD}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Rôle">
          {ROLES.map((option) => (
            <Chip
              key={option.label}
              href={href({ role: option.value || null })}
              active={role === option.value}
            >
              {option.label}
            </Chip>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Statut">
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
        {company && (
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Entreprise">
            <Chip href={href({ company: null })} active>
              {companyName || "Une entreprise"} ×
              <span className="sr-only"> (retirer ce filtre)</span>
            </Chip>
          </div>
        )}
      </div>

      {error && <Notice tone="danger">{error}</Notice>}
      {loading && <Skeleton label="Chargement des utilisateurs" />}

      {data && (
        <>
          <p className="text-encre-douce" aria-live="polite">
            {data.total} compte{data.total > 1 ? "s" : ""}
          </p>
          {data.items.length === 0 ? (
            <EmptyState title="Aucun compte ne correspond.">
              {filtered ? (
                <>
                  Retirez un filtre ou cherchez un autre nom.{" "}
                  <Link href={pathname} className="underline">
                    Tout afficher
                  </Link>
                </>
              ) : (
                "Aucune entreprise n'a encore de compte."
              )}
            </EmptyState>
          ) : (
            <>
              <div className="hidden overflow-x-auto rounded-xl border border-trait bg-surface md:block">
                <table className="w-full text-left">
                  <thead className="border-b border-trait text-sm text-encre-douce">
                    <tr>
                      {sortHeader("Nom", "name")}
                      <th scope="col" className="px-4 py-3">
                        Entreprise
                      </th>
                      <th scope="col" className="px-4 py-3">
                        Rôle
                      </th>
                      <th scope="col" className="px-4 py-3">
                        Statut
                      </th>
                      {sortHeader("Dernière connexion", "last_login")}
                      <th scope="col" className="px-4 py-3">
                        <span className="sr-only">Action</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((user) => (
                      <tr key={user.id} className="border-b border-trait last:border-0">
                        <td className="px-4 py-3">
                          <span className="block font-semibold">{user.full_name}</span>
                          <span className="block text-sm text-encre-douce">
                            {user.email ?? "—"}
                          </span>
                        </td>
                        <td className="px-4 py-3">{user.company_name}</td>
                        <td className="px-4 py-3">{roles(user)}</td>
                        <td className="px-4 py-3">
                          <Pill tone={STATUS_TONES[user.status] ?? "neutre"}>
                            {MERCHANT_STATUS_LABELS[user.status] ?? user.status}
                          </Pill>
                        </td>
                        <td className="px-4 py-3">
                          <LastLogin value={user.last_login_at} />
                        </td>
                        <td className="px-4 py-3 text-right">
                          <Link
                            href={`/companies/${user.company_id}`}
                            className="inline-flex min-h-11 items-center gap-1.5 font-semibold underline"
                          >
                            <Building2 aria-hidden="true" className="size-4" />
                            Voir l&apos;entreprise
                            <span className="sr-only"> de {user.full_name}</span>
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <ul aria-label="Comptes" className="space-y-3 md:hidden">
                {data.items.map((user) => (
                  <li key={user.id} className="rounded-xl border border-trait bg-surface p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="font-semibold">{user.full_name}</p>
                        <p className="truncate text-sm text-encre-douce">{user.email ?? "—"}</p>
                      </div>
                      <Pill tone={STATUS_TONES[user.status] ?? "neutre"}>
                        {MERCHANT_STATUS_LABELS[user.status] ?? user.status}
                      </Pill>
                    </div>
                    <p className="mt-2">
                      {user.company_name} · {roles(user)}
                    </p>
                    <p className="text-sm text-encre-douce">
                      Dernière connexion : <LastLogin value={user.last_login_at} />
                    </p>
                    <Link
                      href={`/companies/${user.company_id}`}
                      className="mt-2 inline-flex min-h-11 items-center gap-1.5 font-semibold underline"
                    >
                      Voir l&apos;entreprise<span className="sr-only"> de {user.full_name}</span>
                    </Link>
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
