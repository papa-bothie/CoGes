"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { toApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/queries/keys";

/** Le PNG reçu en adresse `data:` : rien à libérer, utilisable aussi par l'impression. */
function dataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error("logo illisible"));
    reader.readAsDataURL(blob);
  });
}

/**
 * Logo de la boutique (ADR 0111), lu par l'API avec le jeton dans l'en-tête — jamais dans
 * une URL — et rendu en adresse `data:` locale (quelques dizaines de Ko).
 *
 * `version` est `logo_updated_at` de l'entreprise : `null` = pas de logo, rien n'est lu ;
 * une autre date = un autre logo, relu. Le service worker ne garde que `/_next/static`.
 */
export function useCompanyLogo(version: string | null | undefined): string | null {
  const query = useQuery({
    queryKey: queryKeys.companyLogo(version ?? null),
    enabled: Boolean(version),
    staleTime: Infinity,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/companies/me/logo", {
        parseAs: "blob",
      });
      if (!response.ok || !data) throw toApiError(response.status, error);
      return dataUrl(data as Blob);
    },
  });
  return version ? (query.data ?? null) : null;
}
