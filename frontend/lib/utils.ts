import { createCn } from "cn/config";

/**
 * Fusion de classes Tailwind. Les rôles typographiques de `app/globals.css` (`text-heading`,
 * `text-figure`…) y sont déclarés comme **tailles** : sans cela, la fusion les prendrait pour
 * des couleurs et les supprimerait dès qu'une vraie couleur (`text-foreground`) les suit.
 */
export const cn = createCn({
  extend: {
    classGroups: {
      "font-size": [{ text: ["2xs", "page-title", "heading", "figure", "figure-sm"] }],
    },
  },
});
