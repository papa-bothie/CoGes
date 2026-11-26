/**
 * Contenu de la page d'accueil publique (prompt 37), fourni par le propriétaire.
 *
 * Un numéro vide ou factice est refusé par `content/vitrine.test.ts` (ADR 0115) : la vitrine
 * ne part jamais en production sans un vrai contact.
 */
import offres from "./offres.json";

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
   * Section « Nos offres » (prompt 41, ADR 0132) : Pro et Business, Premium sur devis. Une
   * seule source, partagée avec « Mon abonnement » et testée contre la table `plans`.
   */
  pricing: offres.plans,
} as const;

/** Lien `wa.me` vers le support, message prérempli (aucun appel réseau : un simple lien). */
export function whatsappLink(): string {
  // `encodeURIComponent` (%20) plutôt que `URLSearchParams` (+), que WhatsApp lit mal.
  return `https://wa.me/${vitrine.whatsappNumber}?text=${encodeURIComponent(vitrine.whatsappMessage)}`;
}
