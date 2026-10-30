/**
 * Session de l'administration (ADR 0089), calquée sur celle du front commerçant
 * (ADR 0006, 0048) mais **à part** : autre cookie de rafraîchissement
 * (`coges_platform_refresh`, chemin `/api/v1/platform/auth`), autre indicateur, autre
 * verrou et autre canal. Les deux sessions ne se croisent jamais.
 */
import { networkError, toApiError } from "@/lib/api/errors";

import { tokenStore } from "./token-store";

export const SESSION_MARKER = "coges_admin_session";
/** Une session de l'administration dure 12 h au plus (ADR 0105). */
const MARKER_MAX_AGE_SECONDS = 12 * 3600;
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

/**
 * Étape suivante après le mot de passe (ADR 0105) : `verify` (le code de l'application ou
 * un code de secours), ou `enroll` (aucune double authentification encore). Le jeton
 * intermédiaire vit 5 minutes, sert une fois, et ne quitte jamais la mémoire de la page.
 */
export type LoginStep = { step: "enroll" | "verify"; challenge_token: string; expires_in: number };

export type Enrollment = {
  secret: string;
  otpauth_uri: string;
  qr_svg: string;
  account: string;
  issuer: string;
};

async function post(path: string, payload: unknown): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, {
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
  return body;
}

/** Première étape : le mot de passe. Aucune session n'est ouverte ici. */
export async function login(email: string, password: string): Promise<LoginStep> {
  return (await post("/api/v1/platform/auth/login", { email, password })) as LoginStep;
}

/** Le collègue invité choisit son mot de passe, puis enrôle sa double authentification. */
export async function acceptInvitation(token: string, password: string): Promise<LoginStep> {
  return (await post("/api/v1/platform/auth/accept-invitation", { token, password })) as LoginStep;
}

/** Le secret proposé : QR code et clé texte, actif seulement après le premier code. */
export async function startEnrollment(challengeToken: string): Promise<Enrollment> {
  return (await post("/api/v1/platform/auth/mfa/enrollment", {
    challenge_token: challengeToken,
  })) as Enrollment;
}

/** Premier code juste : session ouverte ; rend les codes de secours, montrés une fois. */
export async function confirmEnrollment(challengeToken: string, code: string): Promise<string[]> {
  const body = (await post("/api/v1/platform/auth/mfa/enrollment/confirm", {
    challenge_token: challengeToken,
    code,
  })) as TokenResponse & { recovery_codes: string[] };
  acceptTokens(body);
  return body.recovery_codes;
}

/** Seconde étape : le code de l'application, ou un code de secours. */
export async function verifyMfa(
  challengeToken: string,
  proof: { code: string } | { recovery_code: string },
): Promise<void> {
  acceptTokens(
    (await post("/api/v1/platform/auth/mfa/verify", {
      challenge_token: challengeToken,
      ...proof,
    })) as TokenResponse,
  );
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
