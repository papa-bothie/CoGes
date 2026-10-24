"use client";

import { useEffect, useSyncExternalStore } from "react";

import { setSessionMarker } from "@/lib/auth/session";
import { acceptSupportFragment, isSupportMode } from "@/lib/auth/support";
import { labels } from "@/lib/labels";

const t = labels.support;

const noSubscription = () => () => undefined;

/**
 * Lit le jeton du fragment, l'efface de l'adresse, puis ouvre l'accueil de la boutique.
 * Le fragment ne part jamais vers un serveur : ni Caddy ni Next ne le voient. Sans
 * fragment (lien déjà servi, rechargé, incomplet) : on le dit.
 */
export function SupportEntry() {
  const withoutToken = useSyncExternalStore(
    noSubscription,
    () => window.location.hash === "",
    () => false,
  );

  useEffect(() => {
    if (withoutToken) return;
    // Idempotent : rejoué (Strict Mode), l'effet trouve le fragment déjà lu et le jeton
    // déjà gardé pour l'onglet.
    if (acceptSupportFragment(window.location.hash) || isSupportMode()) {
      // Indicateur pour `proxy.ts` seulement ; il ne donne aucun droit.
      setSessionMarker();
      window.location.replace(new URL("/dashboard", window.location.origin).href);
    } else {
      // Fragment effacé mais inutilisable : la page, rechargée sans lui, le dira.
      window.location.replace(window.location.href);
    }
  }, [withoutToken]);

  if (!withoutToken) {
    return (
      <p role="status" className="text-lg text-encre-2">
        {t.opening}
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <h1 className="text-[28px] leading-tight font-extrabold">{t.invalidTitle}</h1>
      <p className="text-lg text-encre-2">{t.invalidBody}</p>
    </div>
  );
}
