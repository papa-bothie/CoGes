"use client";

import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";

import { useCompanyLocale, useMe } from "@/hooks/use-me";
import { api, unwrap } from "@/lib/api/client";
import { formatClock } from "@/lib/format/date";
import { labels } from "@/lib/labels";

const t = labels.support;

export const SUPPORT_ACCESS_QUERY_KEY = ["companies", "me", "support-access"] as const;

/**
 * « Accès support actif depuis 10:15, par l'équipe CoGes, jusqu'à 12:15 » (ADR 0092) :
 * visible par **tous** les utilisateurs de l'entreprise, toute la durée de l'accès. Relu
 * toutes les 60 s et au retour sur l'onglet ; rien quand aucun accès n'est ouvert.
 */
export function SupportBanner({ now = () => Date.now() }: { now?: () => number }) {
  const me = useMe();
  const { timeZone } = useCompanyLocale();
  const { data } = useQuery({
    queryKey: SUPPORT_ACCESS_QUERY_KEY,
    queryFn: () => unwrap(api.GET("/api/v1/companies/me/support-access")),
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });
  const session = data?.session;
  if (!session || Date.parse(session.expires_at) <= now()) return null;

  return (
    <div
      role="status"
      className="flex items-start gap-3 rounded-lg border border-warning/30 bg-warning/5 px-4 py-3 text-sm text-warning-ink"
    >
      <ShieldCheck className="size-5 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className="font-medium">
          {t.banner(
            formatClock(session.started_at, timeZone),
            formatClock(session.expires_at, timeZone),
          )}
        </p>
        {me.data?.via_support && <p>{t.readOnly}</p>}
      </div>
    </div>
  );
}
