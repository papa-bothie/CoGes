"use client";

import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import {
  dismissInvite,
  installState,
  promptInstall,
  SERVER_INSTALL_STATE,
  shouldInvite,
  subscribeInstall,
} from "@/lib/pwa/install";
import { labels } from "@/lib/labels";

const t = labels.pwa;

/** L'état d'installation, suivi hors de React (événements du navigateur). */
export function useInstall() {
  return useSyncExternalStore(subscribeInstall, installState, () => SERVER_INSTALL_STATE);
}

/**
 * Invitation discrète à installer (ADR 0102) : une fois, après quelques ouvertures, ignorable,
 * jamais sur la connexion ni pendant une vente ; plus jamais une fois installée.
 */
export function InstallInvite() {
  const state = useInstall();
  const pathname = usePathname();
  if (!shouldInvite(state, pathname)) return null;
  return (
    <aside
      aria-label={t.install}
      className="flex flex-wrap items-center justify-between gap-3 rounded-carte border border-border bg-card px-4 py-3"
    >
      <p className="font-semibold">{state.canPrompt ? t.installInvite : t.iosHelp}</p>
      <div className="flex gap-2">
        {state.canPrompt && <Button onClick={() => void promptInstall()}>{t.install}</Button>}
        <Button variant="outline" onClick={dismissInvite}>
          {t.installLater}
        </Button>
      </div>
    </aside>
  );
}
