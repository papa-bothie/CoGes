"use client";

import { useQueryClient } from "@tanstack/react-query";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { watchInstall } from "@/lib/pwa/install";
import { startPwa, updateManager } from "@/lib/pwa/register";
import { labels } from "@/lib/labels";

/**
 * Application installable (ADR 0102) : enregistre le service worker, compte les ouvertures et
 * garde l'invite d'installation, et propose la mise à jour à chaque changement d'écran — elle
 * n'a lieu qu'à un moment sûr. La seule bannière : la version refusée par le serveur, après une
 * mise à jour qui n'a pas suffi.
 */
export function PwaProvider() {
  const queryClient = useQueryClient();
  const pathname = usePathname();
  const [outdated, setOutdated] = useState(false);
  const first = useRef(true);

  useEffect(() => watchInstall(), []);
  useEffect(() => startPwa(queryClient, () => setOutdated(true)), [queryClient]);

  // Changement d'écran par un lien : un moment sûr possible (pas le premier affichage).
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    void updateManager()?.consider("navigation");
  }, [pathname]);

  if (!outdated) return null;
  return (
    <div
      role="status"
      className="fixed inset-x-4 bottom-24 z-50 mx-auto flex max-w-md flex-wrap items-center justify-between gap-3 rounded-carte border border-border bg-card p-4 shadow-lg md:bottom-6"
    >
      <p className="font-semibold">{labels.pwa.outdated}</p>
      <Button onClick={() => window.location.reload()}>{labels.pwa.outdatedReload}</Button>
    </div>
  );
}
