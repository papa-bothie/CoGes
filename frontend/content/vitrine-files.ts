/**
 * Fichiers de `public/vitrine/`, nommés un par un (prompt 37, ADR 0115) : `proxy.ts` ne laisse
 * passer sans connexion que ceux-là, jamais un motif large. Un test vérifie que la liste
 * correspond exactement au dossier.
 */
export const VITRINE_FILES: readonly string[] = [
  "apercu-ordinateur.webp",
  "apercu-telephone.webp",
  "illustration-chiffres.svg",
  "illustration-stock.svg",
  "partage.png",
];
