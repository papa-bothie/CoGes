/**
 * Signaux entre le client de l'API et la mise à jour de l'application (ADR 0102), sans
 * dépendance entre les deux modules.
 */
export const FRONT_VERSION_HEADER = "X-CoGes-Front";
/** Version de ce front, envoyée à l'API pour qu'elle refuse une version trop ancienne (426). */
export const FRONT_VERSION = process.env.NEXT_PUBLIC_APP_VERSION ?? "0.0.0";

export const pwaSignals = typeof EventTarget === "undefined" ? null : new EventTarget();

export function signalOutdated(): void {
  pwaSignals?.dispatchEvent(new Event("outdated"));
}
