/**
 * Client REST typé : `openapi-fetch` sur les types générés depuis `backend/openapi.json`.
 *
 * Les appels partent vers `/api/v1/*` **sur l'origine du front**, que Next réécrit vers
 * l'API (ADR 0047). Le `fetch` fourni ci-dessous ajoute le jeton d'accès, et sur un 401
 * tente **un** rafraîchissement puis rejoue la requête une seule fois.
 */
import createClient from "openapi-fetch";

import { expireSession, refreshSession, type RefreshOutcome } from "@/lib/auth/session";
import { tokenStore } from "@/lib/auth/token-store";
import type { paths } from "@/types/api";

import { networkError, toApiError } from "./errors";

/** Routes qui ne doivent jamais déclencher de rafraîchissement automatique. */
const SESSION_ENDPOINTS = ["/api/v1/auth/login", "/api/v1/auth/refresh", "/api/v1/auth/logout"];

function isSessionEndpoint(url: string): boolean {
  const { pathname } = new URL(url, "http://localhost");
  return SESSION_ENDPOINTS.includes(pathname);
}

function unauthenticated(): Response {
  return new Response(
    JSON.stringify({
      error: { code: "authentication_required", message: "Session expirée.", details: {} },
    }),
    { status: 401, headers: { "Content-Type": "application/json" } },
  );
}

export type AuthFetchDeps = {
  fetch: (request: Request) => Promise<Response>;
  refresh: () => Promise<RefreshOutcome>;
  onExpired: () => void;
  token: { fresh: () => string | null; get: () => string | null };
};

export function createAuthFetch(deps: AuthFetchDeps) {
  const send = (request: Request, token: string | null): Promise<Response> => {
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return deps.fetch(request);
  };

  return async function authFetch(request: Request): Promise<Response> {
    if (isSessionEndpoint(request.url)) return deps.fetch(request);

    // Copie prise **avant** l'envoi : le corps d'une requête ne se lit qu'une fois.
    const retry = request.clone();

    let token = deps.token.fresh();
    if (!token) {
      const outcome = await deps.refresh();
      if (outcome === "unauthenticated") {
        deps.onExpired();
        return unauthenticated();
      }
      token = deps.token.get();
    }

    const response = await send(request, token);
    if (response.status !== 401) return response;

    // Jeton refusé (clé tournée, session révoquée…) : un seul nouvel essai.
    const outcome = await deps.refresh();
    if (outcome === "ok") return send(retry, deps.token.get());
    if (outcome === "unauthenticated") deps.onExpired();
    return response;
  };
}

const authFetch = createAuthFetch({
  fetch: (request) => fetch(request),
  refresh: refreshSession,
  onExpired: expireSession,
  token: tokenStore,
});

export const api = createClient<paths>({
  baseUrl: typeof window === "undefined" ? "http://localhost" : window.location.origin,
  fetch: authFetch,
});

type Result<T> = { data?: T; error?: unknown; response: Response };

/**
 * Attend un appel `api.GET/POST…` et renvoie ses données, ou lève une `ApiError`.
 * Pratique comme `queryFn` / `mutationFn` de TanStack Query.
 */
export async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  let result: Result<T>;
  try {
    result = await call;
  } catch {
    throw networkError();
  }
  if (!result.response.ok) throw toApiError(result.response.status, result.error);
  return result.data as T;
}
