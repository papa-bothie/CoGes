import { CheckCircle2, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { RUBRIQUE_CLASSES, type Rubrique } from "./rubrique";

/**
 * Bandeau de la maquette v2 (« Il restera 13 500 F à payer », « Choisissez le client pour lui
 * faire crédit ») : teinte de la rubrique, texte gras à l'encre de la rubrique, rayon 16 px.
 * `role="status"` : annoncé quand il apparaît, sans voler le focus.
 */
export function Banner({
  rubrique = "stock",
  icon: Icon,
  children,
  action,
  className,
}: {
  rubrique?: Rubrique;
  icon?: LucideIcon;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const tone = RUBRIQUE_CLASSES[rubrique];
  return (
    <div
      role="status"
      className={cn(
        "flex items-center gap-3 rounded-champ px-4 py-3.5 font-bold",
        tone.tint,
        tone.ink,
        className,
      )}
    >
      {Icon && <Icon className="size-5 shrink-0" aria-hidden />}
      <div className="flex-1">{children}</div>
      {action}
    </div>
  );
}

/**
 * Écran de succès (maquette 02d) : grand disque vert, titre, précision et actions.
 * Le titre prend le focus à l'affichage : c'est le nouvel état de l'écran.
 */
export function SuccessScreen({
  title,
  detail,
  actions,
  rubrique = "ventes",
}: {
  title: ReactNode;
  detail?: ReactNode;
  actions?: ReactNode;
  rubrique?: Rubrique;
}) {
  const tone = RUBRIQUE_CLASSES[rubrique];
  return (
    <div className="flex flex-col items-center gap-5 py-10 text-center" role="status">
      <span
        className={cn("flex size-24 items-center justify-center rounded-full", tone.tint, tone.ink)}
        aria-hidden
      >
        <CheckCircle2 className="size-14" />
      </span>
      <h2 className="text-titre-page" tabIndex={-1}>
        {title}
      </h2>
      {detail && <div className="text-libelle font-semibold text-muted-foreground">{detail}</div>}
      {actions && <div className="flex w-full max-w-md flex-col gap-3">{actions}</div>}
    </div>
  );
}

/** Message d'aide sous un champ : 16 px, gris, ou à l'encre d'une rubrique. */
export function FieldHint({
  children,
  rubrique,
  id,
}: {
  children: ReactNode;
  rubrique?: Rubrique;
  id?: string;
}) {
  return (
    <p
      id={id}
      className={cn(
        "text-corps",
        rubrique ? cn("font-semibold", RUBRIQUE_CLASSES[rubrique].ink) : "text-muted-foreground",
      )}
    >
      {children}
    </p>
  );
}
