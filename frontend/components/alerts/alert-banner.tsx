import { ChevronRight, type LucideIcon } from "lucide-react";
import Link from "next/link";

import { cn } from "@/lib/utils";

const TONES = {
  danger: "border-destructive/30 bg-destructive/5 text-danger-ink",
  warning: "border-warning/30 bg-warning/5 text-warning-ink",
  neutral: "border-border bg-card text-foreground",
} as const;

/**
 * Bandeau d'alerte cliquable : orange pour un seuil bas, rouge pour une rupture, neutre pour
 * une dette échue ; détail à droite et flèche vers l'élément concerné.
 */
export function AlertBanner({
  icon: Icon,
  title,
  detail,
  href,
  tone = "neutral",
}: {
  icon: LucideIcon;
  title: string;
  detail?: string;
  href?: string;
  tone?: keyof typeof TONES;
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
    TONES[tone],
    href &&
      "hover:bg-muted/60 focus-visible:ring-ring/50 transition-colors outline-none focus-visible:ring-3",
  );
  return href ? (
    <Link href={href} className={className}>
      {content}
    </Link>
  ) : (
    <div role="status" className={className}>
      {content}
    </div>
  );
}
