"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useMe } from "@/components/admin-shell";
import { StatusBadge } from "@/components/status-badge";
import { StatusDialog, type StatusTarget } from "@/components/status-dialog";
import { SubscriptionCard } from "@/components/subscription-card";
import { SupportAccessCard } from "@/components/support-access-card";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { CompanyDetail } from "@/lib/api/schema";
import { ROLE_LABELS, formatDate, formatDateTime } from "@/lib/format";

export function CompanyDetailView({
  companyId,
  merchantUrl,
}: {
  companyId: string;
  merchantUrl: string;
}) {
  const me = useMe();
  const [company, setCompany] = useState<CompanyDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  // Un paiement ou un changement de statut d'abonnement peut changer l'accès : relu.
  const [version, setVersion] = useState(0);

  useEffect(() => {
    unwrap(
      api.GET("/api/v1/platform/companies/{company_id}", {
        params: { path: { company_id: companyId } },
      }),
    ).then(setCompany, (caught: unknown) => setError(errorMessage(caught)));
  }, [companyId, version]);

  if (error) {
    return (
      <p role="alert" className="rounded bg-danger-teinte px-3 py-2 text-danger">
        {error}
      </p>
    );
  }
  if (!company) return <p aria-live="polite">Chargement…</p>;

  const target: StatusTarget = company.status === "suspended" ? "active" : "suspended";
  const canChange = me?.role === "administrator";

  async function changeStatus(reason: string) {
    const updated = await unwrap(
      api.PATCH("/api/v1/platform/companies/{company_id}/status", {
        params: { path: { company_id: companyId } },
        body: { status: target, reason },
      }),
    );
    setCompany(updated);
    setDialogOpen(false);
    setNotice(updated.status === "suspended" ? "Entreprise suspendue." : "Entreprise réactivée.");
  }

  return (
    <section aria-labelledby="titre-entreprise" className="space-y-6">
      <Link href="/companies" className="text-encre-douce underline">
        ← Entreprises
      </Link>
      <div className="flex flex-wrap items-center gap-3">
        <h1 id="titre-entreprise" className="text-2xl font-bold">
          {company.name}
        </h1>
        <StatusBadge status={company.status} />
      </div>
      {notice && (
        <p role="status" className="rounded bg-succes-teinte px-3 py-2 text-succes">
          {notice}
        </p>
      )}

      <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-[max-content_1fr]">
        <dt className="text-encre-douce">Code</dt>
        <dd>{company.slug}</dd>
        <dt className="text-encre-douce">Inscription</dt>
        <dd>{formatDate(company.created_at)}</dd>
        <dt className="text-encre-douce">Comptes actifs</dt>
        <dd>{company.user_count}</dd>
        <dt className="text-encre-douce">Dernière activité</dt>
        <dd>{formatDateTime(company.last_activity_at)}</dd>
      </dl>

      {canChange && (
        <button
          type="button"
          onClick={() => setDialogOpen(true)}
          className={`rounded px-4 py-2 font-semibold ${
            target === "suspended" ? "bg-danger text-surface" : "bg-accent text-accent-encre"
          }`}
        >
          {target === "suspended" ? "Suspendre l'entreprise" : "Réactiver l'entreprise"}
        </button>
      )}

      <SubscriptionCard
        companyId={companyId}
        canChange={canChange}
        onAccessChanged={() => setVersion((n) => n + 1)}
      />

      <SupportAccessCard
        companyId={companyId}
        suspended={company.status === "suspended"}
        merchantUrl={merchantUrl}
      />

      <section aria-labelledby="titre-comptes" className="space-y-2">
        <h2 id="titre-comptes" className="text-xl font-bold">
          Comptes
        </h2>
        <div className="overflow-x-auto rounded border border-trait bg-surface">
          <table className="w-full text-left">
            <thead className="border-b border-trait text-sm text-encre-douce">
              <tr>
                <th scope="col" className="px-3 py-2">
                  Nom
                </th>
                <th scope="col" className="px-3 py-2">
                  Rôle
                </th>
                <th scope="col" className="px-3 py-2">
                  Dernière connexion
                </th>
              </tr>
            </thead>
            <tbody>
              {company.users.map((user) => (
                <tr key={user.id} className="border-b border-trait last:border-0">
                  <td className="px-3 py-2">
                    {user.full_name}
                    {!user.is_active && (
                      <span className="ml-2 text-sm text-encre-douce">(désactivé)</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {user.roles.map((role) => ROLE_LABELS[role] ?? role).join(", ") || "—"}
                  </td>
                  <td className="px-3 py-2">{formatDateTime(user.last_login_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <StatusDialog
        companyName={company.name}
        target={target}
        open={dialogOpen}
        onCancel={() => setDialogOpen(false)}
        onConfirm={changeStatus}
      />
    </section>
  );
}
