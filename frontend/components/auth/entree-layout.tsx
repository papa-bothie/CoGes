import type { ReactNode } from "react";

import { BrandLogo } from "@/components/brand/brand";

export type EntreePanel = {
  /** La phrase : « Votre boutique, simplement. » */
  tagline: string;
  pitch: string;
  /** Pastilles des rubriques, montrées à partir de 768 px. */
  pills: readonly string[];
};

/**
 * Mise en page des pages d'entrée, maquette v2 (écran 25), partagée par la connexion,
 * l'inscription et la vérification (prompt 39, bloc S, ADR 0123) : à gauche le panneau vert
 * (logo, phrase, texte, pastilles), à droite une colonne de 440 px au plus (titre, formulaire,
 * liens légaux). Sur téléphone, le panneau se réduit au logo et à la phrase, au-dessus.
 */
export function EntreeLayout({ panel, children }: { panel: EntreePanel; children: ReactNode }) {
  return (
    <main className="flex min-h-dvh flex-col bg-background md:flex-row">
      <section
        data-entree-panneau
        className="flex flex-col justify-between gap-8 bg-ventes-teinte px-6 py-8 text-marque md:min-h-dvh md:flex-1 md:px-12 md:py-14"
      >
        <BrandLogo className="h-auto w-[220px] md:w-[318px]" />
        <div className="max-w-[420px] space-y-3">
          <p className="text-[34px] leading-[1.15] font-extrabold md:text-[44px]">
            {panel.tagline}
          </p>
          <p className="text-lg text-marque/85 md:text-xl">{panel.pitch}</p>
        </div>
        <ul className="hidden flex-wrap gap-2.5 md:flex" aria-hidden>
          {panel.pills.map((pill) => (
            <li key={pill} className="rounded-full bg-card px-4 py-2.5 font-bold">
              {pill}
            </li>
          ))}
        </ul>
      </section>
      <section className="flex flex-1 items-center justify-center px-4 py-10 md:px-12">
        <div data-entree-colonne className="w-full max-w-[440px] space-y-6">
          {children}
        </div>
      </section>
    </main>
  );
}
