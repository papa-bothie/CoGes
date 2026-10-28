/**
 * Client REST typé : `openapi-fetch` sur les types générés depuis `backend/openapi.json`.
 *
 * Les appels partent vers `/api/v1/*` **sur l'origine du front**, que Next réécrit vers
 * l'API (ADR 0047). Le `fetch` fourni ci-dessous ajoute le jeton d'accès, et sur un 401
 * tente **un** rafraîchissement puis rejoue la requête une seule fois.
 */
import createClient from "openapi-fetch";

import {
  COMPANY_SUSPENDED,
  expireSession,
  refreshSession,
  suspendSession,
  type RefreshOutcome,
} from "@/lib/auth/session";
import { SUPPORT_SESSION_ENDED } from "@/lib/auth/support";
import { tokenStore } from "@/lib/auth/token-store";
import type { paths } from "@/types/api";

import { networkError, toApiError } from "./errors";
import { FRONT_VERSION, FRONT_VERSION_HEADER, signalOutdated } from "@/lib/pwa/signals";

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
  /** Entreprise suspendue (403 `company_suspended`, ADR 0089). */
  onSuspended: () => void;
  token: { fresh: () => string | null; get: () => string | null };
};

export function createAuthFetch(deps: AuthFetchDeps) {
  // Chaque requête dit sa version ; une version refusée (426) déclenche la mise à jour à un
  // moment sûr (ADR 0102).
  const versioned = async (request: Request): Promise<Response> => {
    request.headers.set(FRONT_VERSION_HEADER, FRONT_VERSION);
    const response = await deps.fetch(request);
    if (response.status === 426) signalOutdated();
    return response;
  };
  const send = (request: Request, token: string | null): Promise<Response> => {
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return versioned(request);
  };

  /** Un 403 ne dit « suspendue » que par son code : on lit une copie du corps. */
  const isSuspension = async (response: Response): Promise<boolean> => {
    if (response.status !== 403) return false;
    try {
      const body = (await response.clone().json()) as { error?: { code?: string } };
      return body.error?.code === COMPANY_SUSPENDED;
    } catch {
      return false;
    }
  };

  /** Accès support fermé ou échu (ADR 0092) : rien à rafraîchir, c'est terminé. */
  const isSupportEnd = async (response: Response): Promise<boolean> => {
    try {
      const body = (await response.clone().json()) as { error?: { code?: string } };
      return body.error?.code === SUPPORT_SESSION_ENDED;
    } catch {
      return false;
    }
  };

  return async function authFetch(request: Request): Promise<Response> {
    if (isSessionEndpoint(request.url)) return versioned(request);

    // Copie prise **avant** l'envoi : le corps d'une requête ne se lit qu'une fois.
    const retry = request.clone();

    let token = deps.token.fresh();
    if (!token) {
      const outcome = await deps.refresh();
      if (outcome === "unauthenticated") {
        deps.onExpired();
        return unauthenticated();
      }
      if (outcome === "suspended") {
        deps.onSuspended();
        return unauthenticated();
      }
      token = deps.token.get();
    }

    const response = await send(request, token);
    if (await isSuspension(response)) {
      deps.onSuspended();
      return response;
    }
    if (response.status !== 401) return response;
    if (await isSupportEnd(response)) {
      deps.onExpired();
      return response;
    }

    // Une autre requête a déjà fait tourner le jeton pendant que celle-ci était en route :
    // on rejoue avec le jeton neuf, sans seconde rotation (ADR 0088).
    const current = deps.token.get();
    if (current && current !== token) return send(retry, current);

    // Jeton refusé (clé tournée, session révoquée…) : un seul nouvel essai.
    const outcome = await deps.refresh();
    if (outcome === "ok") return send(retry, deps.token.get());
    if (outcome === "unauthenticated") deps.onExpired();
    if (outcome === "suspended") deps.onSuspended();
    return response;
  };
}

const authFetch = createAuthFetch({
  fetch: (request) => fetch(request),
  refresh: refreshSession,
  onExpired: expireSession,
  onSuspended: suspendSession,
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
  if (!result.response.ok) {
    throw toApiError(
      result.response.status,
      result.error,
      result.response.headers?.get("x-request-id") ?? null,
    );
  }
  return result.data as T;
}
