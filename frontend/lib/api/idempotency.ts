"use client";

import { useCallback, useState } from "react";

/** En-tête posé sur toute écriture financière (ADR 0027). */
export const IDEMPOTENCY_HEADER = "Idempotency-Key";

/**
 * Clé d'idempotence d'un formulaire : créée à son ouverture, **gardée** tant que
 * l'écriture n'a pas réussi — une nouvelle tentative après une coupure réseau rejoue
 * la même demande au lieu d'en créer une seconde — puis renouvelée après succès.
 *
 * Garder la clé après un refus métier est sans danger : le serveur annule la clé avec
 * la transaction, et une demande corrigée repart comme une demande neuve.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function useIdempotencyKey() {
  const [key, setKey] = useState(() => crypto.randomUUID());
  const renew = useCallback(() => setKey(crypto.randomUUID()), []);
  /**
   * Reprend la clé d'un brouillon retrouvé (ADR 0101) : un envoi interrompu puis relancé
   * rejoue avec la **même** clé, jamais deux écritures (ADR 0027, 0085). Ignore ce qui n'est
   * pas une clé.
   */
  const restore = useCallback((value: unknown) => {
    if (typeof value === "string" && UUID.test(value)) setKey(value);
  }, []);
  return { key, renew, restore, headers: { [IDEMPOTENCY_HEADER]: key } };
}
