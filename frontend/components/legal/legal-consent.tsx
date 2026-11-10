"use client";

import { labels } from "@/lib/labels";

const t = labels.legal.acceptance;

/**
 * La case « J'ai lu et j'accepte… » (prompt 36, ADR 0117), avec ses deux liens ouverts dans
 * un nouvel onglet pour ne pas perdre la saisie. Contrôlée : le parent garde l'état et
 * n'active son bouton qu'une fois cochée. Réutilisée telle quelle par l'inscription (lot 30),
 * qui l'exige aussi à la création du compte gérant.
 */
export function LegalConsent({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  const link =
    "inline-flex min-h-cible items-center rounded-mini font-bold text-success-ink underline underline-offset-4 outline-none focus-visible:ring-3 focus-visible:ring-ring/60";
  return (
    <div className="space-y-4">
      <ul className="space-y-1">
        <li>
          <a href="/conditions" target="_blank" rel="noopener" className={link}>
            {t.conditionsLink}
            <span className="sr-only"> {t.opensNewTab}</span>
          </a>
        </li>
        <li>
          <a href="/confidentialite" target="_blank" rel="noopener" className={link}>
            {t.privacyLink}
            <span className="sr-only"> {t.opensNewTab}</span>
          </a>
        </li>
      </ul>
      <label className="flex min-h-cible cursor-pointer items-start gap-3 rounded-carte border-2 border-input bg-card p-4 has-[:checked]:border-primary has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/60">
        <input
          type="checkbox"
          name="legal_consent"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
          className="mt-0.5 size-6 shrink-0 cursor-pointer accent-primary outline-none"
        />
        <span className="text-base leading-snug font-semibold">{t.consent}</span>
      </label>
    </div>
  );
}
