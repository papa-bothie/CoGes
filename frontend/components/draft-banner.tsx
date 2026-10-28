import { History } from "lucide-react";

import { labels } from "@/lib/labels";

const t = labels.draft;

/**
 * Bandeau discret d'un brouillon retrouvé (ADR 0101) : jamais une fenêtre bloquante. « Effacer »
 * remet le formulaire à zéro et oublie le brouillon.
 */
export function DraftBanner({ onClear }: { onClear: () => void }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-champ bg-voile px-4 py-2">
      <p role="status" className="flex items-center gap-2 font-semibold">
        <History aria-hidden className="size-5 shrink-0" />
        {t.restored}
      </p>
      <button
        type="button"
        onClick={onClear}
        aria-label={t.clearLabel}
        className="min-h-cible rounded-touche px-3 font-bold underline underline-offset-2 outline-none hover:bg-card focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        {t.clear}
      </button>
    </div>
  );
}
