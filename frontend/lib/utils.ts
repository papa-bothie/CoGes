import { createCn } from "cn/config";

/**
 * Fusion de classes Tailwind. Les rôles typographiques de `app/globals.css` (`text-heading`,
 * `text-figure`, `text-libelle`…) y sont déclarés comme **tailles** : sans cela, la fusion les
 * prendrait pour des couleurs et les supprimerait dès qu'une vraie couleur
 * (`text-primary-foreground`) les suit. Idem pour les rayons et les tailles de la maquette v2
 * (`rounded-carte`, `min-h-bouton`…).
 */
export const cn = createCn({
  extend: {
    theme: {
      text: [
        "2xs",
        "page-title",
        "heading",
        "figure",
        "figure-sm",
        "mini",
        "petit",
        "corps",
        "libelle",
        "titre-page",
        "titre-carte",
        "chiffre",
        "chiffre-heros",
      ],
      radius: ["carte", "bouton", "champ", "tuile", "touche", "mini"],
      spacing: [
        "cible",
        "bouton",
        "bouton-principal",
        "champ-montant",
        "touche",
        "marge-page",
        "sections",
        "carte",
      ],
      container: ["page"],
    },
  },
});
