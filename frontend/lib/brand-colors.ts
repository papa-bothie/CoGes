/**
 * Couleurs du manifeste de l'application installable (ADR 0102). Le manifeste exige des
 * valeurs en clair, que le thème CSS ne peut pas fournir : c'est la seule exception au
 * garde-fou des couleurs (`lib/no-hardcoded-colors.test.ts`), et `lib/brand-colors.test.ts`
 * vérifie qu'elles restent égales aux jetons de `app/globals.css`.
 */
export const BRAND_COLORS = {
  /** `--coges-vert-marque` (clair) : barre d'état et barre de titre. */
  theme: "#024a2c",
  /** `--coges-papier` (clair) : écran de lancement. */
  background: "#fbf8f3",
} as const;
