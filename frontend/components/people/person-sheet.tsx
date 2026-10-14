"use client";

import { Phone } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { RUBRIQUE_CLASSES, type Rubrique } from "@/components/kit/rubrique";
import { Can } from "@/hooks/use-permission";
import type { PermissionRule } from "@/lib/permissions";
import { labels } from "@/lib/labels";
import { initials } from "@/lib/people";
import { phoneDigits } from "@/lib/phone";
import { cn } from "@/lib/utils";

const t = labels.peopleScreens;
const OUTLINE = cn(
  "inline-flex min-h-bouton items-center gap-2.5 rounded-bouton border-2 border-input bg-card px-5 text-[17px] font-bold text-foreground",
  "outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50",
);

/** Lien `tel:` : le numéro sénégalais complet (+221), sinon tel quel. */
function telHref(phone: string): string {
  const digits = phoneDigits(phone);
  return digits.length === 9 ? `tel:+221${digits}` : `tel:${phone.replace(/\s/g, "")}`;
}

/** En-tête des fiches 14 et 16 : initiales, nom, téléphone, « Appeler » et « Modifier ». */
export function PersonHeader({
  name,
  rubrique,
  subtitle,
  phone,
  editHref,
  editPermission,
}: {
  name: string;
  rubrique: Rubrique;
  subtitle: string;
  phone: string | null;
  editHref: string;
  editPermission: PermissionRule;
}) {
  return (
    <div className="flex flex-wrap items-center gap-4">
      <span
        aria-hidden
        className={cn(
          "flex size-[76px] shrink-0 items-center justify-center rounded-full text-[28px] font-extrabold",
          RUBRIQUE_CLASSES[rubrique].solid,
        )}
      >
        {initials(name)}
      </span>
      <div className="min-w-0 flex-[1_1_240px]">
        <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{name}</h1>
        <p className="text-lg numeric text-muted-foreground">{subtitle}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {phone && (
          <a href={telHref(phone)} className={OUTLINE}>
            <Phone className="size-[22px]" aria-hidden />
            {t.call}
          </a>
        )}
        <Can permission={editPermission}>
          <Link href={editHref} className={OUTLINE}>
            {t.edit}
          </Link>
        </Can>
      </div>
    </div>
  );
}

/** Une tuile de fiche : un libellé, un grand chiffre, une précision. Sans rubrique : neutre. */
export function SheetTile({
  rubrique,
  label,
  value,
  detail,
  detailInk,
  small = false,
}: {
  rubrique?: Rubrique;
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  /** La précision en couleur (« Depuis 12 jours », « À payer avant le 10 octobre »). */
  detailInk?: string;
  /** Une valeur en mots (« Riz, huile, sucre ») plutôt qu'un chiffre. */
  small?: boolean;
}) {
  const tone = rubrique ? RUBRIQUE_CLASSES[rubrique] : null;
  return (
    <div
      className={cn("flex flex-col gap-1 rounded-[20px] p-[18px]", tone ? tone.tint : "bg-voile")}
    >
      <span className="font-semibold">{label}</span>
      <span
        className={cn(
          "font-extrabold numeric",
          small ? "text-[22px] leading-snug" : "text-[34px] leading-tight",
          tone ? tone.ink : "text-foreground",
        )}
      >
        {value}
      </span>
      {detail && (
        <span className={detailInk ? cn("font-semibold", detailInk) : "text-muted-foreground"}>
          {detail}
        </span>
      )}
    </div>
  );
}

/** Les deux vues d'une fiche (« Ses achats », « Ses paiements ») dans une carte. */
export function HistoryTabs({
  rubrique,
  label,
  tabs,
}: {
  rubrique: Rubrique;
  label: string;
  tabs: { id: string; label: string; content: ReactNode }[];
}) {
  const [active, setActive] = useState(tabs[0]?.id);
  const current = tabs.find((tab) => tab.id === active) ?? tabs[0];
  return (
    <section className="rounded-carte border border-border bg-card p-[22px]">
      <div role="tablist" aria-label={label} className="mb-1.5 flex flex-wrap gap-2">
        {tabs.map((tab) => {
          const selected = tab.id === current?.id;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={`tab-${tab.id}`}
              aria-selected={selected}
              aria-controls={`panel-${tab.id}`}
              onClick={() => setActive(tab.id)}
              className={cn(
                "min-h-[52px] rounded-full border-2 px-5 text-base font-bold",
                "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                selected
                  ? cn("border-transparent", RUBRIQUE_CLASSES[rubrique].solid)
                  : "border-input bg-card text-foreground hover:bg-voile",
              )}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
      {current && (
        <div role="tabpanel" id={`panel-${current.id}`} aria-labelledby={`tab-${current.id}`}>
          {current.content}
        </div>
      )}
    </section>
  );
}
