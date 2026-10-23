/**
 * Jeton d'accès **en mémoire uniquement** (ADR 0006) : ni `localStorage`, ni cookie
 * lisible. Un rechargement de page le perd ; le cookie `httpOnly` de rafraîchissement
 * permet d'en obtenir un nouveau.
 */

type State = { token: string; expiresAt: number };

let state: State | null = null;

/** Marge avant expiration sous laquelle on rafraîchit plutôt que d'envoyer le jeton. */
export const EXPIRY_MARGIN_MS = 60_000;

export const tokenStore = {
  get(): string | null {
    return state?.token ?? null;
  },

  /** Jeton encore valide au-delà de la marge, sinon `null`. */
  fresh(now: number = Date.now()): string | null {
    if (!state || state.expiresAt - now <= EXPIRY_MARGIN_MS) return null;
    return state.token;
  },

  set(token: string, expiresInSeconds: number, now: number = Date.now()): void {
    state = { token, expiresAt: now + expiresInSeconds * 1000 };
  },

  clear(): void {
    state = null;
  },
};
