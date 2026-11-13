import { texte } from "@/content/vitrine-texte";
import { cn } from "@/lib/utils";

import styles from "./vitrine.module.css";

const { title, rotation } = texte.hero;

/**
 * Titre du hero (prompt 38, A1, ADR 0116) : « [Les ventes | Le stock | L'argent] » se
 * relaient au-dessus de « de votre boutique, au même endroit. », qui ne bouge pas, pendant
 * trois tours, puis la zone s'arrête sur « Les ventes, le stock et l'argent ».
 *
 * Composant serveur, CSS seul, aucune hydratation. Le `<h1>` porte la phrase complète en
 * texte réel (lecteur d'écran, moteurs, sans script) ; la version animée est `aria-hidden`.
 * La phrase de fin occupe la case commune dès le premier affichage (invisible) : la hauteur
 * de la zone est la sienne à toute largeur, rien ne bouge quand elle paraît.
 */
export function HeroTitle({ className }: { className?: string }) {
  return (
    <h1 id="titre" className={className}>
      <span className="sr-only">{title}</span>
      <span aria-hidden className="block">
        <span className={cn(styles.zone, "text-primary")} data-zone="titre">
          {rotation.mots.map((mot) => (
            <span key={mot} className={styles.mot} data-mot={mot}>
              {mot}
            </span>
          ))}
          <span className={styles.complet} data-complet>
            {rotation.complet}
          </span>
        </span>
        <span className="block">{rotation.suite}</span>
      </span>
    </h1>
  );
}
