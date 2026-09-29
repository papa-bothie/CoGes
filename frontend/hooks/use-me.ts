"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";

export const ME_QUERY_KEY = ["auth", "me"] as const;

/** Utilisateur, rôles, permissions et entreprise de la session (`GET /auth/me`). */
export function useMe() {
  return useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: () => unwrap(api.GET("/api/v1/auth/me")),
    staleTime: 5 * 60_000,
  });
}

/** Fuseau et devise de l'entreprise, pour les formats d'affichage. */
export function useCompanyLocale(): { timeZone: string; currency: string } {
  const { data } = useMe();
  return {
    timeZone: data?.company.timezone ?? "UTC",
    currency: data?.company.currency ?? "XOF",
  };
}
