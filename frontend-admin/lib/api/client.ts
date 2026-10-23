/**
 * Client typé de l'administration : `openapi-fetch` sur les types générés depuis
 * `backend/openapi.json`. Seules les routes `/api/v1/platform/*` sont appelées ; le
 * jeton d'accès est ajouté ici, et sur un 401 on tente **un** rafraîchissement.
 */
import createClient from "openapi-fetch";

import { expireSession, refreshSession, type RefreshOutcome } from "@/lib/auth/session";
import { tokenStore } from "@/lib/auth/token-store";
import type { paths } from "@/types/api";

import { networkError, toApiError } from "./errors";

const SESSION_ENDPOINTS = [
  "/api/v1/platform/auth/login",
  "/api/v1/platform/auth/refresh",
  "/api/v1/platform/auth/logout",
];

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
    const { pathname } = new URL(request.url, "http://localhost");
    if (SESSION_ENDPOINTS.includes(pathname)) return deps.fetch(request);
    const retry = request.clone();

    let token = deps.token.fresh();
    if (!token) {
      const outcome = await deps.refresh();
      if (outcome === "unauthenticated") {
        deps.onExpired();
        return new Response(
          JSON.stringify({
            error: { code: "authentication_required", message: "Session expirée.", details: {} },
          }),
          { status: 401, headers: { "Content-Type": "application/json" } },
        );
      }
      token = deps.token.get();
    }

    const response = await send(request, token);
    if (response.status !== 401) return response;
    const outcome = await deps.refresh();
    if (outcome === "ok") return send(retry, deps.token.get());
    if (outcome === "unauthenticated") deps.onExpired();
    return response;
  };
}

export const api = createClient<paths>({
  baseUrl: typeof window === "undefined" ? "http://localhost" : window.location.origin,
  fetch: createAuthFetch({
    fetch: (request) => fetch(request),
    refresh: refreshSession,
    onExpired: expireSession,
    token: tokenStore,
  }),
});

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Rend la donnée, ou lève une `ApiError` lisible. */
export async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  let result: Result<T>;
  try {
    result = await call;
  } catch {
    throw networkError();
  }
  if (result.error !== undefined || !result.response.ok) {
    throw toApiError(result.response.status, result.error);
  }
  return result.data as T;
}
