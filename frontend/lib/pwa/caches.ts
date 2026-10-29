/** Vidage des caches de l'application (ADR 0102), sans dépendance : appelé par la session. */

/**
 * Déconnexion : plus rien de la session dans le Cache Storage de cet appareil. Le worker vide
 * tout puis remet la page hors ligne (aucune donnée) ; la page ne vide elle-même que sans
 * worker, sinon elle effacerait ce qu'il vient de remettre (prompt 32, P2).
 */
export function clearAppCaches(): void {
  try {
    const worker = navigator.serviceWorker?.controller;
    if (worker) {
      worker.postMessage({ type: "LOGOUT" });
      return;
    }
  } catch {
    // Pas de worker : la page vide elle-même.
  }
  try {
    void caches
      ?.keys()
      .then((names) => Promise.all(names.map((name) => caches.delete(name))))
      .catch(() => undefined);
  } catch {
    // Cache Storage indisponible (navigation privée) : il n'y a rien à vider.
  }
}
