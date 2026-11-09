import { Check } from "lucide-react";

import { texte } from "@/content/vitrine-texte";
import { formatAmount, formatFigure } from "@/lib/format/money";
import { cn } from "@/lib/utils";

import styles from "./vitrine.module.css";

const { caisse } = texte.hero;
const total = caisse.lignes.reduce((sum, ligne) => sum + ligne.quantite * ligne.prix, 0);

/**
 * Mini-caisse du hero (prompt 38, A9, ADR 0116), à la place de l'illustration : les trois
 * articles arrivent l'un après l'autre, puis le total, puis « Encaissé ». Une seule
 * séquence de 3,2 s, CSS seul, composant serveur.
 *
 * Tout est dans le flux dès le premier affichage (seules l'opacité et la position bougent) :
 * aucun décalage. L'état de repos du CSS est le ticket complet : mouvement réduit, fin de
 * séquence et navigateur sans animation montrent la même chose. La version visible est
 * `aria-hidden` ; `caisse.resume` la dit aux lecteurs d'écran.
 */
export function MiniCaisse() {
  return (
    <div>
      <p className="sr-only">{caisse.resume}</p>
      <div
        aria-hidden
        data-caisse
        className="rounded-carte border border-border bg-card p-6 shadow-xl md:p-7"
      >
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-border pb-4">
          <span className="text-titre-carte whitespace-nowrap">{caisse.titre}</span>
          <span className="text-sm text-muted-foreground">{caisse.boutique}</span>
        </div>
        <ul className="divide-y divide-border">
          {caisse.lignes.map((ligne, index) => (
            <li
              key={ligne.article}
              className={cn(styles.etape, "flex items-center justify-between gap-4 py-3")}
              data-caisse-etape={index + 1}
            >
              <span className="min-w-0">
                <span className="block font-semibold">{ligne.article}</span>
                <span className="block text-sm text-muted-foreground tabular-nums">
                  {ligne.quantite} × {formatFigure(String(ligne.prix))}
                </span>
              </span>
              <span className="font-bold whitespace-nowrap tabular-nums">
                {formatAmount(String(ligne.quantite * ligne.prix))}
              </span>
            </li>
          ))}
        </ul>
        <div
          className={cn(
            styles.etape,
            "flex items-baseline justify-between gap-4 border-t-2 border-foreground pt-4",
          )}
          data-caisse-etape="total"
        >
          <span className="text-libelle">{caisse.total}</span>
          <span className="text-chiffre whitespace-nowrap tabular-nums">
            {formatAmount(String(total))}
          </span>
        </div>
        <div className="mt-4 flex items-center justify-between gap-3">
          <span className="text-sm text-muted-foreground">{caisse.moyen}</span>
          <span
            className={cn(
              styles.etape,
              "inline-flex items-center gap-2 rounded-full bg-success px-4 py-2 font-bold text-success-foreground",
            )}
            data-caisse-etape="encaisse"
          >
            <Check className="size-5" strokeWidth={3} />
            {caisse.encaisse}
          </span>
        </div>
      </div>
    </div>
  );
}
