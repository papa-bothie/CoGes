import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { RUBRIQUE_CLASSES, type Rubrique } from "./rubrique";

/**
 * Tuile chiffrée de l'accueil (maquette 01) : teinte de la rubrique, disque d'icône plein,
 * libellé, grand chiffre, précision colorée. Cliquable si `href` est donné.
 * `compact` : la version téléphone (26), sans disque, chiffre plus petit.
 */
export function StatTile({
  rubrique,
  icon: Icon,
  label,
  value,
  detail,
  href,
  compact = false,
}: {
  rubrique: Rubrique;
  icon?: LucideIcon;
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  href?: string;
  compact?: boolean;
}) {
  const tone = RUBRIQUE_CLASSES[rubrique];
  const body = (
    <>
      {Icon && !compact && (
        <span
          className={cn("flex size-12 items-center justify-center rounded-champ", tone.solid)}
          aria-hidden
        >
          <Icon className="size-[22px]" />
        </span>
      )}
      <span className={cn("font-semibold", compact ? "text-petit" : "text-libelle")}>{label}</span>
      <span
        className={cn(
          "font-extrabold numeric",
          compact ? "text-[22px] leading-7" : "text-[36px] leading-[1.1]",
          compact && tone.ink,
        )}
      >
        {value}
      </span>
      {detail && !compact && <span className={cn("font-semibold", tone.ink)}>{detail}</span>}
    </>
  );
  const className = cn(
    "flex flex-col text-foreground",
    compact ? "gap-1 rounded-tuile px-4 py-4" : "min-h-[170px] gap-2.5 rounded-carte p-carte",
    tone.tint,
  );
  return href ? (
    <Link
      href={href}
      className={cn(
        className,
        "outline-none hover:brightness-[0.98] focus-visible:ring-3 focus-visible:ring-ring/50",
      )}
    >
      {body}
    </Link>
  ) : (
    <div className={className}>{body}</div>
  );
}
