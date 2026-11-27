"use client";

import { CalendarClock, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Banner } from "@/components/kit/feedback";
import { useMe } from "@/hooks/use-me";
import { formatDayLong } from "@/lib/format/date";
import { labels } from "@/lib/labels";
import { can } from "@/lib/permissions";
import { cn } from "@/lib/utils";

const t = labels.renewal;

/** Clé du repli « pour aujourd'hui » : par boutique, par étape et par jour. */
export function hiddenKey(companyId: string, stage: string, day: string): string {
  return `coges:renewal-hidden:${companyId}:${stage}:${day}`;
}

function localDay(now: number, timeZone: string): string {
  // `en-CA` écrit la date en AAAA-MM-JJ.
  return new Intl.DateTimeFormat("en-CA", { timeZone }).format(new Date(now));
}

function readHidden(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

/**
 * Bandeau de relance (ADR 0133), de la veille de la fin à J+2, en haut de chaque écran :
 * le gérant (`company:update`) voit le message de l'étape et « Choisir mon offre » ;
 * les autres seulement le dernier rappel, pour prévenir leur gérant. Couleur calme,
 * orange au dernier rappel seulement. Il reste dans le flux de la page : il ne couvre
 * jamais le panier ni l'encaissement. Repliable pour la journée (stockage local).
 */
export function RenewalBanner({ now = () => Date.now() }: { now?: () => number }) {
  const me = useMe();
  const renewal = me.data?.plan?.renewal;
  const company = me.data?.company;
  const manager = can(me.data?.permissions, "company:update");
  const day = company ? localDay(now(), company.timezone) : "";
  const key = renewal && company ? hiddenKey(company.id, renewal.stage, day) : "";
  const [hidden, setHidden] = useState(() => (key ? readHidden(key) : false));

  if (!renewal || !company || me.data?.via_support) return null;
  if (!manager && renewal.stage !== "last") return null;
  if (hidden || readHidden(key)) return null;

  const plan = me.data?.plan?.name ?? "";
  const text = !manager
    ? t.lastOthers
    : renewal.stage === "eve"
      ? t.eve(renewal.kind, plan)
      : renewal.stage === "due"
        ? t.due(renewal.kind, renewal.days_left)
        : t.last;

  const hide = () => {
    try {
      window.localStorage.setItem(key, "1");
    } catch {
      // Sans stockage, le bandeau se replie jusqu'au prochain chargement.
    }
    setHidden(true);
  };

  return (
    <Banner
      rubrique={renewal.stage === "last" ? "stock" : "conseils"}
      icon={CalendarClock}
      className="flex-wrap font-semibold"
      action={
        <div className="flex items-center gap-2">
          {manager && (
            <Link
              href="/settings/subscription"
              className={cn(
                "inline-flex h-cible items-center rounded-champ border-2 border-current px-4 font-bold",
                "focus-visible:outline-2 focus-visible:outline-offset-2",
              )}
            >
              {t.choose}
            </Link>
          )}
          <button
            type="button"
            onClick={hide}
            aria-label={t.hide}
            title={t.hide}
            className="inline-flex size-cible items-center justify-center rounded-champ focus-visible:outline-2"
          >
            <X className="size-5" aria-hidden />
          </button>
        </div>
      }
    >
      <p>{text}</p>
      {manager && (
        <p className="text-sm font-normal">{t.pauseOn(formatDayLong(renewal.pause_on))}</p>
      )}
    </Banner>
  );
}
