/**
 * Mode « accès support » (ADR 0092) : l'équipe CoGes lit la boutique, en lecture seule,
 * avec un jeton remis par l'administration dans le fragment de `/support#token=…`.
 *
 * - Le jeton vit dans le `sessionStorage` **de cet onglet** : un rechargement le garde,
 *   un autre onglet ne le voit pas, fermer l'onglet l'oublie.
 * - Jamais de `/auth/refresh` ni de `/auth/logout` : le cookie de rafraîchissement d'une
 *   vraie session, s'il existait dans ce navigateur, n'est jamais touché.
 * - Le serveur relit la session à chaque requête : fermée ou échue, il répond 401
 *   `support_session_ended`, et l'onglet affiche « L'accès support est terminé ».
 */
import { tokenStore } from "./token-store";

const STORAGE_KEY = "coges_support";
export const SUPPORT_SESSION_ENDED = "support_session_ended";
export const SUPPORT_ENDED_PATH = "/support/termine";

type Stored = { token: string; expiresAt: number };

function storage(): Storage | null {
  try {
    return typeof sessionStorage === "undefined" ? null : sessionStorage;
  } catch {
    return null;
  }
}

function read(): Stored | null {
  try {
    const raw = storage()?.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Stored>;
    return typeof parsed.token === "string" && typeof parsed.expiresAt === "number"
      ? { token: parsed.token, expiresAt: parsed.expiresAt }
      : null;
  } catch {
    return null;
  }
}

/** Cet onglet est-il en accès support ? */
export function isSupportMode(): boolean {
  return read() !== null;
}

/**
 * Lit `#token=…&expires_in=…`, efface aussitôt le fragment de l'adresse (il ne reste ni
 * dans l'historique ni dans la barre), et garde le jeton pour l'onglet. `false` : rien
 * d'utilisable dans le fragment.
 */
export function acceptSupportFragment(hash: string, now: number = Date.now()): boolean {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const token = params.get("token");
  const expiresIn = Number(params.get("expires_in"));
  if (typeof history !== "undefined" && typeof location !== "undefined") {
    history.replaceState(null, "", location.pathname);
  }
  if (!token || !Number.isFinite(expiresIn) || expiresIn <= 0) return false;
  const stored: Stored = { token, expiresAt: now + expiresIn * 1000 };
  try {
    storage()?.setItem(STORAGE_KEY, JSON.stringify(stored));
  } catch {
    // Stockage refusé : le jeton reste en mémoire, l'onglet marche jusqu'au rechargement.
  }
  tokenStore.set(token, expiresIn, now);
  return true;
}

/** À la place d'un rafraîchissement : reprend le jeton de l'onglet s'il n'est pas échu. */
export function restoreSupportToken(now: number = Date.now()): boolean {
  const stored = read();
  if (!stored || stored.expiresAt <= now) return false;
  tokenStore.set(stored.token, Math.floor((stored.expiresAt - now) / 1000), now);
  return true;
}

/** Fin de l'accès : l'onglet oublie le jeton et dit que c'est terminé. */
export function endSupportSession(
  navigate: (url: string) => void = (url) => location.assign(url),
): void {
  try {
    storage()?.removeItem(STORAGE_KEY);
  } catch {
    // Rien à oublier.
  }
  tokenStore.clear();
  if (typeof location !== "undefined" && location.pathname !== SUPPORT_ENDED_PATH) {
    navigate(new URL(SUPPORT_ENDED_PATH, location.origin).href);
  }
}
