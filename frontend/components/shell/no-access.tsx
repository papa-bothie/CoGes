import Link from "next/link";

import { labels } from "@/lib/labels";

const t = labels.noAccess;

/**
 * Écran d'une adresse tapée sans le droit de la page (ADR 0099). La page elle-même n'est
 * pas rendue : aucune donnée chargée, aucun appel d'API inutile. Le serveur, lui, aurait
 * refusé chaque lecture (403).
 */
export function NoAccess({ home }: { home: string | null }) {
  return (
    <section className="mx-auto flex max-w-md flex-col items-center gap-3 py-16 text-center">
      <h1 className="text-titre-page leading-tight">{t.title}</h1>
      <p className="text-lg text-muted-foreground">{t.hint}</p>
      {home && (
        <Link
          href={home}
          className="mt-2 inline-flex min-h-bouton items-center rounded-bouton bg-primary px-5 text-[17px] font-bold text-primary-foreground outline-none hover:bg-primary/90 focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {t.home}
        </Link>
      )}
    </section>
  );
}
