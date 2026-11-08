/**
 * Contenu de la page d'accueil publique (prompt 37), fourni par le propriétaire.
 *
 * ⚠️ VALEURS PROVISOIRES : remplacer le numéro WhatsApp, les horaires et le message avant
 * toute mise en production. Le numéro factice ci-dessous est refusé par le test
 * `content/vitrine.test.ts` (voir l'ADR de la page d'accueil).
 */
export const vitrine = {
  /** Adresse publique du site (balises de partage, sitemap.xml, robots.txt). */
  siteUrl: "https://coges.app",
  /** Numéro WhatsApp du support : format international, chiffres seuls, sans « + » ni espace. */
  whatsappNumber: "221781811756",
  /** Horaires du support, affichés tels quels (pied de page et questions fréquentes). */
  supportHours: "Du lundi au samedi, de 9 h à 19 h",
  /** Message prérempli à l'ouverture de WhatsApp. */
  whatsappMessage: "Bonjour, je voudrais en savoir plus sur CoGes pour ma boutique.",
  /**
   * Section « Tarifs » : `null` tant que les prix ne sont pas arrêtés. S'ils sont fournis, ils
   * reprennent mot pour mot les conditions générales de vente.
   */
  pricing: null,
} as const;

/** Lien `wa.me` vers le support, message prérempli (aucun appel réseau : un simple lien). */
export function whatsappLink(): string {
  // `encodeURIComponent` (%20) plutôt que `URLSearchParams` (+), que WhatsApp lit mal.
  return `https://wa.me/${vitrine.whatsappNumber}?text=${encodeURIComponent(vitrine.whatsappMessage)}`;
}
