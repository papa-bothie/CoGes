"use client";

import { ArrowLeft, History, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useMe } from "@/components/admin-shell";
import { ConfirmDialog, type ConfirmRequest } from "@/components/confirm-dialog";
import { StatusBadge } from "@/components/status-badge";
import { SubscriptionCard } from "@/components/subscription-card";
import { SupportAccessCard } from "@/components/support-access-card";
import { BUTTON, Card, Notice } from "@/components/ui";
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
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
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

  if (error) return <Notice tone="danger">{error}</Notice>;
  if (!company) return <p aria-live="polite">Chargement…</p>;

  const suspended = company.status === "suspended";
  const isAdmin = me?.role === "administrator";
  const name = company.name;

  async function setStatus(status: "active" | "suspended", reason: string) {
    const updated = await unwrap(
      api.PATCH("/api/v1/platform/companies/{company_id}/status", {
        params: { path: { company_id: companyId } },
        body: { status, reason },
      }),
    );
    setCompany(updated);
    setNotice(updated.status === "suspended" ? `${name} est suspendue.` : `${name} est réactivée.`);
  }

  function askStatus() {
    setNotice(null);
    setConfirm(
      suspended
        ? {
            title: `Réactiver ${name} ?`,
            consequence: (
              <p>Ses comptes pourront de nouveau se connecter. Le gérant est prévenu par e-mail.</p>
            ),
            confirmLabel: `Réactiver ${name}`,
            // L'API garde une raison au journal ; une réactivation n'en demande pas ici.
            onConfirm: (reason) => setStatus("active", reason || "Réactivée depuis la fiche"),
          }
        : {
            title: `Suspendre ${name} ?`,
            consequence: (
              <p>
                Personne de {name} ne pourra plus se connecter ; les sessions ouvertes
                s&apos;arrêtent à la prochaine requête. Ses données sont conservées. Le gérant est
                prévenu par e-mail.
              </p>
            ),
            confirmLabel: `Suspendre ${name}`,
            destructive: true,
            requireReason: true,
            onConfirm: (reason) => setStatus("suspended", reason),
          },
    );
  }

  return (
    <section aria-labelledby="titre-entreprise" className="space-y-6">
      <Link
        href="/companies"
        className="inline-flex min-h-11 items-center gap-1.5 text-encre-douce underline"
      >
        <ArrowLeft aria-hidden="true" className="size-4" />
        Entreprises
      </Link>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1 id="titre-entreprise" className="text-2xl font-bold tracking-tight">
            {name}
          </h1>
          <StatusBadge status={company.status} />
        </div>
        {isAdmin && (
          <Link
            href={`/audit?company=${companyId}`}
            className="inline-flex min-h-11 items-center gap-1.5 font-semibold underline"
          >
            <History aria-hidden="true" className="size-4" />
            Historique
          </Link>
        )}
      </div>
      {notice && (
        <Notice tone="succes">
          {notice}{" "}
          {isAdmin && (
            <Link href={`/audit?company=${companyId}`} className="font-semibold underline">
              Voir dans le journal
            </Link>
          )}
        </Notice>
      )}

      <Card aria-label="Identité">
        <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-4">
          <div>
            <dt className="text-sm text-encre-douce">Code</dt>
            <dd className="font-semibold">{company.slug}</dd>
          </div>
          <div>
            <dt className="text-sm text-encre-douce">Inscription</dt>
            <dd className="font-semibold">{formatDate(company.created_at)}</dd>
          </div>
          <div>
            <dt className="text-sm text-encre-douce">Comptes actifs</dt>
            <dd className="font-semibold">{company.user_count}</dd>
          </div>
          <div>
            <dt className="text-sm text-encre-douce">Dernière activité</dt>
            <dd className="font-semibold">{formatDateTime(company.last_activity_at)}</dd>
          </div>
        </dl>
      </Card>

      <SubscriptionCard
        companyId={companyId}
        canChange={isAdmin}
        onAccessChanged={() => setVersion((n) => n + 1)}
      />

      <SupportAccessCard companyId={companyId} suspended={suspended} merchantUrl={merchantUrl} />

      <section aria-labelledby="titre-comptes" className="space-y-2">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="titre-comptes" className="text-xl font-bold">
            Comptes
          </h2>
          <Link href={`/users?company=${companyId}`} className="text-sm font-semibold underline">
            Voir dans Utilisateurs
          </Link>
        </div>
        <div className="overflow-x-auto rounded-xl border border-trait bg-surface">
          <table className="w-full text-left">
            <thead className="border-b border-trait text-sm text-encre-douce">
              <tr>
                <th scope="col" className="px-4 py-3">
                  Nom
                </th>
                <th scope="col" className="px-4 py-3">
                  Rôle
                </th>
                <th scope="col" className="px-4 py-3">
                  Dernière connexion
                </th>
              </tr>
            </thead>
            <tbody>
              {company.users.map((user) => (
                <tr key={user.id} className="border-b border-trait last:border-0">
                  <td className="px-4 py-3">
                    {user.full_name}
                    {!user.is_active && (
                      <span className="ml-2 text-sm text-encre-douce">(désactivé)</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {user.roles.map((role) => ROLE_LABELS[role] ?? role).join(", ") || "—"}
                  </td>
                  <td className="px-4 py-3">{formatDateTime(user.last_login_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {isAdmin && (
        <section
          aria-labelledby="titre-acces"
          className="space-y-3 rounded-xl border border-danger bg-surface p-5"
        >
          <h2 id="titre-acces" className="flex items-center gap-2 text-xl font-bold">
            <ShieldAlert aria-hidden="true" className="size-5 text-danger" />
            Accès de l&apos;entreprise
          </h2>
          <p className="text-encre-douce">
            {suspended
              ? "L'entreprise est suspendue : personne ne peut s'y connecter. Ses données sont conservées."
              : "Suspendre coupe l'accès de tous ses comptes à la prochaine requête. Ses données sont conservées."}
          </p>
          <button
            type="button"
            onClick={askStatus}
            className={suspended ? BUTTON.primary : BUTTON.danger}
          >
            {suspended ? "Réactiver l'entreprise" : "Suspendre l'entreprise"}
          </button>
        </section>
      )}

      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </section>
  );
}
