import { MessageCircle, PauseCircle } from "lucide-react";

import { vitrine } from "@/content/vitrine";
import { labels } from "@/lib/labels";

const t = labels.renewal;

/** Lien `wa.me` vers l'équipe, message prérempli avec le code de la boutique. */
export function pausedWhatsappLink(shop: string): string {
  return `https://wa.me/${vitrine.whatsappNumber}?text=${encodeURIComponent(t.pausedMessage(shop))}`;
}

/**
 * Boutique mise en pause (`company_suspended`, ADR 0133) : un écran chaleureux, les
 * données gardées, et WhatsApp pour payer (le paiement en ligne viendra au lot D).
 */
export function PausedShop({ shop, live }: { shop: string; live: "alert" | "status" }) {
  return (
    <section
      role={live}
      aria-labelledby="boutique-en-pause"
      className="space-y-3 rounded-champ bg-conseils-teinte px-4 py-4 text-conseils-encre"
    >
      <h2 id="boutique-en-pause" className="flex items-center gap-2 text-lg font-bold">
        <PauseCircle className="size-6 shrink-0" aria-hidden />
        {t.pausedTitle}
      </h2>
      <p className="font-semibold">{t.pausedBody}</p>
      <p>{t.pausedHow}</p>
      <a
        href={pausedWhatsappLink(shop)}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex min-h-cible items-center gap-2 rounded-champ bg-ventes px-4 font-bold text-primary-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <MessageCircle className="size-5" aria-hidden />
        {t.pausedWhatsapp}
      </a>
    </section>
  );
}
