/**
 * Session de l'administration (ADR 0089), calquée sur celle du front commerçant
 * (ADR 0006, 0048) mais **à part** : autre cookie de rafraîchissement
 * (`coges_platform_refresh`, chemin `/api/v1/platform/auth`), autre indicateur, autre
 * verrou et autre canal. Les deux sessions ne se croisent jamais.
 */
import { networkError, toApiError } from "@/lib/api/errors";

import { tokenStore } from "./token-store";

export const SESSION_MARKER = "coges_admin_session";
const MARKER_MAX_AGE_SECONDS = 7 * 24 * 3600;
const LOCK_NAME = "coges-admin-refresh";
const CHANNEL_NAME = "coges-admin-auth";

export type RefreshOutcome = "ok" | "unauthenticated" | "unavailable";

type TokenResponse = { access_token: string; expires_in: number };

function secureSuffix(): string {
  return typeof location !== "undefined" && location.protocol === "https:" ? "; Secure" : "";
}

function setSessionMarker(): void {
  document.cookie = `${SESSION_MARKER}=1; Path=/; Max-Age=${MARKER_MAX_AGE_SECONDS}; SameSite=Strict${secureSuffix()}`;
}

function clearSessionMarker(): void {
  document.cookie = `${SESSION_MARKER}=; Path=/; Max-Age=0; SameSite=Strict${secureSuffix()}`;
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
    response = await fetch("/api/v1/platform/auth/refresh", {
      method: "POST",
      credentials: "same-origin",
    });
  } catch {
    return "unavailable";
  }
  if (response.ok) {
    acceptTokens((await response.json()) as TokenResponse);
    return "ok";
  }
  return response.status === 401 ? "unauthenticated" : "unavailable";
}

async function withCrossTabLock(task: () => Promise<RefreshOutcome>): Promise<RefreshOutcome> {
  if (typeof navigator === "undefined" || !navigator.locks) return task();
  return (await navigator.locks.request(LOCK_NAME, task)) as RefreshOutcome;
}

let inFlight: Promise<RefreshOutcome> | null = null;

export function refreshSession(): Promise<RefreshOutcome> {
  inFlight ??= withCrossTabLock(requestRefresh).finally(() => {
    inFlight = null;
  });
  return inFlight;
}

export async function login(email: string, password: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/v1/platform/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch {
    throw networkError();
  }
  const body = await readJson(response);
  if (!response.ok) throw toApiError(response.status, body);
  acceptTokens(body as TokenResponse);
}

/** Le collègue invité choisit son mot de passe ; la session s'ouvre comme une connexion. */
export async function acceptInvitation(token: string, password: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/v1/platform/auth/accept-invitation", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, password }),
    });
  } catch {
    throw networkError();
  }
  const body = await readJson(response);
  if (!response.ok) throw toApiError(response.status, body);
  acceptTokens(body as TokenResponse);
}

function forgetLocally(): void {
  tokenStore.clear();
  clearSessionMarker();
}

let bus: BroadcastChannel | null = null;

function channel(): BroadcastChannel | null {
  if (typeof BroadcastChannel === "undefined") return null;
  bus ??= new BroadcastChannel(CHANNEL_NAME);
  return bus;
}

export async function logout(): Promise<void> {
  if (inFlight) await inFlight.catch(() => undefined);
  try {
    await fetch("/api/v1/platform/auth/logout", { method: "POST", credentials: "same-origin" });
  } catch {
    // Serveur injoignable : on oublie quand même la session ici.
  } finally {
    forgetLocally();
    channel()?.postMessage({ type: "logout" });
  }
}

/** Page de connexion, avec la raison du retour s'il y en a une. */
export function loginUrl(reason?: "expired"): string {
  return reason ? `/login?reason=${reason}` : "/login";
}

/**
 * Session perdue : on oublie tout et on recharge la connexion. Rechargement complet,
 * pas une navigation de Next : aucun état de la session ne doit survivre.
 */
export function expireSession(): void {
  forgetLocally();
  channel()?.postMessage({ type: "logout" });
  if (typeof location !== "undefined" && !location.pathname.startsWith("/login")) {
    location.assign(loginUrl("expired"));
  }
}

export function onLogoutElsewhere(handler: () => void): () => void {
  const target = channel();
  if (!target) return () => undefined;
  const listener = (event: MessageEvent<{ type?: string }>) => {
    if (event.data?.type === "logout") {
      forgetLocally();
      handler();
    }
  };
  target.addEventListener("message", listener);
  return () => target.removeEventListener("message", listener);
}
