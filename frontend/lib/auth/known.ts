/**
 * Marqueur « déjà connu » (prompt 37, ADR 0115) : `coges_known=1` dit seulement que quelqu'un
 * s'est déjà connecté à CoGes sur cet appareil. Sans session, la racine mène alors à la
 * connexion plutôt qu'à la vitrine. Aucun identifiant, aucun droit ; lisible par le script
 * (pas `HttpOnly`) parce que la connexion le pose aussi depuis le navigateur.
 */
export const KNOWN_MARKER = "coges_known";
/** Un an, en secondes. */
export const KNOWN_MAX_AGE_SECONDS = 365 * 24 * 3600;
