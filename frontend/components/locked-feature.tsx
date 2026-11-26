import { Lock, MessageCircle } from "lucide-react";

import { labels } from "@/lib/labels";
import { BUSINESS, upgradeLink } from "@/lib/offres";
import { cn } from "@/lib/utils";

const t = labels.settingsScreens.locked;

/** Badge « Business » d'une fonction réservée à l'offre Business (ADR 0132). */
export function BusinessBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full bg-argent-teinte px-2.5 py-0.5 text-sm font-bold text-argent-encre",
        className,
      )}
    >
      <Lock className="size-3.5" aria-hidden />
      {t.badge}
    </span>
  );
}

/**
 * Une fonction que l'offre de la boutique n'a pas : jamais un 403 brut, toujours cette carte
 * (« Disponible avec Business ») et le chemin pour l'avoir (WhatsApp prérempli, lot D ensuite).
 */
export function LockedFeatureCard({
  title,
  description,
  className,
}: {
  title: string;
  description: string;
  className?: string;
}) {
  return (
    <div
      className={cn("flex flex-col gap-2.5 rounded-tuile p-[18px]", className)}
      data-testid="locked-feature"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-lg font-extrabold">{title}</h3>
        <BusinessBadge />
      </div>
      <p className="font-bold">{t.title(BUSINESS.name)}</p>
      <p className="text-encre-2">{description}</p>
      <a
        href={upgradeLink()}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex min-h-[54px] items-center justify-center gap-2 rounded-champ bg-primary px-5 font-bold text-primary-foreground outline-none hover:bg-primary/90 focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <MessageCircle className="size-5" aria-hidden />
        {t.upgrade(BUSINESS.name)}
      </a>
    </div>
  );
}
