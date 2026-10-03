import { ChevronRight, type LucideIcon } from "lucide-react";
import Link from "next/link";

import type { Schemas } from "@/lib/api/schema";
import { cn } from "@/lib/utils";

export type AlertSeverity = Schemas["NotificationSeverity"];

// La couleur suit la gravité **renvoyée par le serveur** (ADR 0059) : attention (orange)
// par défaut, danger (rouge) si `critical`. Jamais neutre : une alerte demande d'agir.
const TONES: Record<AlertSeverity, string> = {
  warning: "border-warning/30 bg-warning/5 text-warning-ink",
  critical: "border-destructive/30 bg-destructive/5 text-danger-ink",
};

/**
 * Bandeau d'alerte cliquable : détail à droite et flèche vers l'élément concerné.
 */
export function AlertBanner({
  icon: Icon,
  title,
  detail,
  href,
  severity = "warning",
}: {
  icon: LucideIcon;
  title: string;
  detail?: string;
  href?: string;
  severity?: AlertSeverity;
}) {
  const content = (
    <>
      <Icon className="size-5 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1 truncate font-medium">{title}</span>
      {detail && <span className="text-sm numeric text-muted-foreground">{detail}</span>}
      {href && <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />}
    </>
  );
  const className = cn(
    "flex items-center gap-3 rounded-lg border px-4 py-3 text-sm",
    TONES[severity],
    href &&
      "hover:bg-muted/60 focus-visible:ring-ring/50 transition-colors outline-none focus-visible:ring-3",
  );
  return href ? (
    <Link href={href} data-severity={severity} className={className}>
      {content}
    </Link>
  ) : (
    <div role="status" data-severity={severity} className={className}>
      {content}
    </div>
  );
}
