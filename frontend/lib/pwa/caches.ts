/** Vidage des caches de l'application (ADR 0102), sans dépendance : appelé par la session. */

/** Déconnexion : plus rien de l'application dans le Cache Storage de cet appareil. */
export function clearAppCaches(): void {
  try {
    navigator.serviceWorker?.controller?.postMessage({ type: "LOGOUT" });
  } catch {
    // Pas de worker : rien à lui dire.
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
