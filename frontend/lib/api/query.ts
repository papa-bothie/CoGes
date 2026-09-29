import { MutationCache, QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { errorMessage, isApiError } from "./errors";

declare module "@tanstack/react-query" {
  interface Register {
    mutationMeta: {
      /** `false` quand le formulaire affiche lui-même l'erreur (champs, 409…). */
      toastError?: boolean;
    };
  }
}

/**
 * Cache des lectures et des mutations. Aucune donnée métier n'y est **calculée** : il ne
 * garde que des réponses de l'API, invalidées après chaque écriture.
 */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        // Une erreur 4xx ne se corrige pas en réessayant.
        retry: (failureCount, error) =>
          !(isApiError(error) && error.status >= 400 && error.status < 500) && failureCount < 2,
      },
      mutations: { retry: false },
    },
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        if (mutation.meta?.toastError === false) return;
        toast.error(errorMessage(error));
      },
    }),
  });
}
