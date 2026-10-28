import type { Metadata } from "next";

import { buttonVariants } from "@/components/ui/button";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.pwa.offlineTitle };

/**
 * Page sans réseau (ADR 0102) : la seule page que le service worker garde, montrée quand une
 * navigation échoue faute de connexion. Statique, sans donnée de la boutique, même ton que
 * l'écran d'erreur (ADR 0085).
 */
export default function OfflinePage() {
  return (
    <main className="grid min-h-dvh place-items-center bg-background p-6">
      <div className="flex max-w-md flex-col items-center gap-4 text-center">
        <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">
          {labels.pwa.offlineTitle}
        </h1>
        <p className="text-lg text-muted-foreground">{labels.pwa.offlineBody}</p>
        {/* Un lien vide recharge l'adresse demandée : il marche sans aucun script, ceux de
            l'application n'étant peut-être pas encore gardés sur l'appareil. */}
        <a href="" className={buttonVariants()}>
          {labels.pwa.offlineRetry}
        </a>
      </div>
    </main>
  );
}
