import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { errorMessage, isApiError, isTransient } from "./errors";

/** Nouveaux essais d'une LECTURE coupée par le réseau : 2, 4 puis 8 s (ADR 0085). */
export const TRANSIENT_RETRIES = 3;

export function retryDelay(attempt: number): number {
  return 2000 * 2 ** attempt;
}

export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (isTransient(error)) return failureCount < TRANSIENT_RETRIES;
  // Une erreur 4xx ne se corrige pas en réessayant.
  if (isApiError(error) && error.status >= 400 && error.status < 500) return false;
  return failureCount < 2;
}

declare module "@tanstack/react-query" {
  interface Register {
    mutationMeta: {
      /** `false` quand le formulaire affiche lui-même l'erreur (champs, 409…). */
      toastError?: boolean;
    };
  }
}

/** Clé de `GET /auth/me` (doublée de `hooks/use-me.ts`, que ce module ne peut pas importer). */
const ME_KEY = ["auth", "me"] as const;

/**
 * Un droit retiré par le gérant vaut dès la requête suivante côté serveur (ADR 0099) : au
 * premier 403 `permission_denied`, l'identité est relue pour que le menu, les tuiles et la
 * garde de page suivent, sans attendre la reconnexion.
 */
export function refreshIdentityOnDenial(client: QueryClient, error: unknown): void {
  if (isApiError(error) && error.status === 403 && error.code === "permission_denied") {
    void client.invalidateQueries({ queryKey: ME_KEY });
  }
}

/**
 * Cache des lectures et des mutations. Aucune donnée métier n'y est **calculée** : il ne
 * garde que des réponses de l'API, invalidées après chaque écriture.
 */
export function makeQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: shouldRetry,
        retryDelay: (attempt, error) => (isTransient(error) ? retryDelay(attempt) : 1000),
      },
      // Jamais de rejeu silencieux d'une écriture : la saisie reste à l'écran et
      // « Réessayer » repart avec la même clé d'idempotence (ADR 0052, ADR 0085).
      mutations: { retry: false },
    },
    queryCache: new QueryCache({
      onError: (error) => refreshIdentityOnDenial(client, error),
    }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        refreshIdentityOnDenial(client, error);
        if (mutation.meta?.toastError === false) return;
        toast.error(errorMessage(error));
      },
    }),
  });
  return client;
}
