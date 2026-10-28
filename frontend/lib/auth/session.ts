/**
 * Cycle de vie de la session côté navigateur (ADR 0006 et 0048).
 *
 * - Le **refresh token** vit dans un cookie `httpOnly` (chemin `/api/v1/auth`) : ce
 *   module ne le voit jamais, il appelle seulement `/auth/refresh`.
 * - Un seul rafraîchissement à la fois, **tous onglets confondus** (Web Locks) : deux
 *   rotations simultanées du même jeton seraient prises pour un rejeu, et le serveur
 *   révoquerait toute la famille de sessions.
 * - Le cookie `coges_session=1` n'est qu'un **indicateur** pour `proxy.ts` (qui ne voit
 *   pas le cookie de rafraîchissement) : il ne donne aucun droit.
 */
import { networkError, toApiError } from "@/lib/api/errors";
import type { LoginRequest, TokenResponse } from "@/lib/api/schema";
import { clearOwnDrafts } from "@/lib/drafts";

import { DEFAULT_NEXT, safeNext } from "./safe-next";
import { endSupportSession, isSupportMode, restoreSupportToken } from "./support";
import { tokenStore } from "./token-store";

export const SESSION_MARKER = "coges_session";
const MARKER_MAX_AGE_SECONDS = 7 * 24 * 3600; // durée du refresh token
const LOCK_NAME = "coges-auth-refresh";
const CHANNEL_NAME = "coges-auth";

/** `suspended` : l'administration a coupé l'accès de l'entreprise (ADR 0089). */
export type RefreshOutcome = "ok" | "unauthenticated" | "unavailable" | "suspended";

/** Code d'erreur de l'API quand l'entreprise est suspendue (403). */
export const COMPANY_SUSPENDED = "company_suspended";

function secureSuffix(): string {
  return typeof location !== "undefined" && location.protocol === "https:" ? "; Secure" : "";
}

export function setSessionMarker(): void {
  document.cookie = `${SESSION_MARKER}=1; Path=/; Max-Age=${MARKER_MAX_AGE_SECONDS}; SameSite=Lax${secureSuffix()}`;
}

export function clearSessionMarker(): void {
  document.cookie = `${SESSION_MARKER}=; Path=/; Max-Age=0; SameSite=Lax${secureSuffix()}`;
}

function acceptTokens(body: TokenResponse): void {
  tokenStore.set(body.access_token, body.expires_in);
  setSessionMarker();
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

async function requestRefresh(): Promise<RefreshOutcome> {
  let response: Response;
  try {
    response = await fetch("/api/v1/auth/refresh", { method: "POST", credentials: "same-origin" });
  } catch {
    return "unavailable";
  }
  if (response.ok) {
    acceptTokens((await response.json()) as TokenResponse);
    return "ok";
  }
  if (
    response.status === 403 &&
    toApiError(403, await readJson(response)).code === COMPANY_SUSPENDED
  ) {
    return "suspended";
  }
  return response.status === 401 ? "unauthenticated" : "unavailable";
}

/** Attente maximale du verrou des onglets : un onglet figé ne bloque pas les autres. */
export const LOCK_WAIT_MS = 10_000;

async function withCrossTabLock(task: () => Promise<RefreshOutcome>): Promise<RefreshOutcome> {
  if (typeof navigator === "undefined" || !navigator.locks) return task();
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), LOCK_WAIT_MS);
  try {
    return (await navigator.locks.request(
      LOCK_NAME,
      { signal: abort.signal },
      task,
    )) as RefreshOutcome;
  } catch (error) {
    // Verrou jamais obtenu (ADR 0088) : on n'enverra pas une rotation concurrente.
    if (error instanceof DOMException && error.name === "AbortError") return "unavailable";
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

let inFlight: Promise<RefreshOutcome> | null = null;

/** Rafraîchit le jeton d'accès. Les appels concurrents partagent la même requête. */
export function refreshSession(): Promise<RefreshOutcome> {
  // Accès support (ADR 0092) : aucun cookie à faire tourner, le jeton de l'onglet suffit.
  if (isSupportMode()) return Promise.resolve(restoreSupportToken() ? "ok" : "unauthenticated");
  inFlight ??= withCrossTabLock(requestRefresh).finally(() => {
    inFlight = null;
  });
  return inFlight;
}

export async function login(payload: LoginRequest): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/v1/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    throw networkError();
  }
  const body = await readJson(response);
  if (!response.ok) throw toApiError(response.status, body);
  acceptTokens(body as TokenResponse);
}

let bus: BroadcastChannel | null = null;

/**
 * **Une seule** instance par onglet, pour émettre comme pour écouter : un canal ne
 * reçoit jamais ses propres messages, alors qu'une seconde instance dans le même onglet
 * les recevrait — et l'onglet qui expire se redirigerait deux fois.
 */
function channel(): BroadcastChannel | null {
  if (typeof BroadcastChannel === "undefined") return null;
  bus ??= new BroadcastChannel(CHANNEL_NAME);
  return bus;
}

function forgetLocally(): void {
  tokenStore.clear();
  clearSessionMarker();
  // Ce qui reste sur l'appareil ne doit pas survivre à la session (ADR 0101).
  clearOwnDrafts();
}

function announceLogout(): void {
  channel()?.postMessage({ type: "logout" });
}

/** Déconnexion volontaire : révoque la famille de sessions côté serveur. */
export async function logout(): Promise<void> {
  // Accès support : surtout pas `/auth/logout`, qui révoquerait une vraie session.
  if (isSupportMode()) return endSupportSession();
  // Un rafraîchissement en cours poserait un jeton neuf **après** l'oubli local, et la
  // personne resterait connectée dans cet onglet (ADR 0088) : on l'attend d'abord.
  if (inFlight) await inFlight.catch(() => undefined);
  try {
    await fetch("/api/v1/auth/logout", { method: "POST", credentials: "same-origin" });
  } catch {
    // Le serveur injoignable n'empêche pas d'oublier la session localement.
  } finally {
    forgetLocally();
    announceLogout();
  }
}

export function loginUrl(reason?: "expired" | "logout" | "suspended"): string {
  const params = new URLSearchParams();
  if (reason) params.set("reason", reason);
  if (reason === "expired" && typeof location !== "undefined") {
    const next = safeNext(location.pathname + location.search, location.origin);
    if (next !== DEFAULT_NEXT) params.set("next", next);
  }
  const query = params.toString();
  return query ? `/login?${query}` : "/login";
}

/** Session perdue (refresh refusé) : on oublie tout et on retourne à la connexion. */
export function expireSession(): void {
  if (isSupportMode()) return endSupportSession();
  forgetLocally();
  announceLogout();
  if (typeof location !== "undefined" && !location.pathname.startsWith("/login")) {
    location.assign(loginUrl("expired"));
  }
}

/**
 * Entreprise suspendue en cours de session (ADR 0089) : la session est oubliée, et la
 * page de connexion dit pourquoi — jamais une erreur technique.
 */
export function suspendSession(): void {
  if (isSupportMode()) return endSupportSession();
  forgetLocally();
  announceLogout();
  if (typeof location !== "undefined" && !location.pathname.startsWith("/login")) {
    location.assign(loginUrl("suspended"));
  }
}

/** Un autre onglet s'est déconnecté : celui-ci suit. Renvoie la fonction d'arrêt. */
export function onLogoutElsewhere(handler: () => void): () => void {
  const target = channel();
  if (!target) return () => undefined;
  const listener = (event: MessageEvent<{ type?: string }>) => {
    // Un onglet d'accès support ne suit pas la déconnexion d'une vraie session.
    if (event.data?.type === "logout" && !isSupportMode()) {
      forgetLocally();
      handler();
    }
  };
  target.addEventListener("message", listener);
  return () => target.removeEventListener("message", listener);
}
