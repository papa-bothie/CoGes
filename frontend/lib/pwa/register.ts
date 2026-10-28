import type { QueryClient } from "@tanstack/react-query";

import { hasUnsentDrafts } from "@/hooks/use-draft";

import { pwaSignals } from "./signals";
import { CHECK_EVERY_MS, isChunkLoadError, UpdateManager } from "./update";

/**
 * Branche le service worker et la mise à jour invisible dans le navigateur (ADR 0102). En
 * production seulement : en développement, un worker garderait des fichiers qui changent à
 * chaque frappe.
 */

/** Écrans d'une vente ou d'un retour en cours : jamais de rechargement tant qu'on y est. */
const IN_PROGRESS = /^\/sales\/(new|[^/]+\/edit|[^/]+\/returns\/new)\/?$/;

let manager: UpdateManager | null = null;

function session(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function pwaEnabled(): boolean {
  return (
    process.env.NODE_ENV === "production" &&
    typeof navigator !== "undefined" &&
    "serviceWorker" in navigator
  );
}

/** Le manager, une fois l'application lancée ; `null` hors production. */
export function updateManager(): UpdateManager | null {
  return manager;
}

export function startPwa(queryClient: QueryClient, onOutdated: () => void): () => void {
  if (!pwaEnabled() || manager) return () => undefined;
  let registration: ServiceWorkerRegistration | null = null;

  const activateWaiting = () =>
    new Promise<boolean>((resolve) => {
      const waiting = registration?.waiting;
      if (!waiting) return resolve(false);
      const done = () => resolve(true);
      navigator.serviceWorker.addEventListener("controllerchange", done, { once: true });
      waiting.postMessage({ type: "SKIP_WAITING" });
      // Le worker ne répond pas : on recharge quand même, la page restera cohérente.
      setTimeout(done, 5_000);
    });

  const current = new UpdateManager({
    pendingWrites: () => queryClient.isMutating(),
    unsentInput: () => hasUnsentDrafts() || IN_PROGRESS.test(window.location.pathname),
    activateWaiting,
    reload: () => window.location.reload(),
    now: () => Date.now(),
    session: session(),
    showOutdated: onOutdated,
  });
  manager = current;

  const watch = (reg: ServiceWorkerRegistration) => {
    // Un worker « installé » alors qu'un autre contrôle la page : une nouvelle version attend.
    const note = (worker: ServiceWorker | null) => {
      if (worker && navigator.serviceWorker.controller) current.workerWaiting();
    };
    note(reg.waiting);
    reg.addEventListener("updatefound", () => {
      const installing = reg.installing;
      installing?.addEventListener("statechange", () => {
        if (installing.state === "installed") note(installing);
      });
    });
  };

  void navigator.serviceWorker
    .register("/sw.js", { scope: "/", updateViaCache: "none" })
    .then((reg) => {
      registration = reg;
      watch(reg);
      // Lancement : une version déjà prête s'active avant que la personne ne commence.
      void current.consider("launch");
    })
    .catch(() => undefined);

  const onVisibility = () => {
    if (document.visibilityState === "hidden") {
      current.pageHidden();
      return;
    }
    void registration?.update().catch(() => undefined);
    void current.pageVisible();
  };
  const onError = (event: ErrorEvent) => {
    if (isChunkLoadError(event.error ?? event.message)) void current.chunkFailed();
  };
  const onRejection = (event: PromiseRejectionEvent) => {
    if (isChunkLoadError(event.reason)) void current.chunkFailed();
  };
  const onOutdatedSignal = () => {
    void registration?.update().catch(() => undefined);
    void current.outdated();
  };
  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("error", onError);
  window.addEventListener("unhandledrejection", onRejection);
  pwaSignals?.addEventListener("outdated", onOutdatedSignal);
  // Toutes les heures : les 24 h d'attente ; toutes les 6 h : chercher une version.
  const hourly = window.setInterval(() => void current.consider("idle"), 60 * 60 * 1000);
  const check = window.setInterval(
    () => void registration?.update().catch(() => undefined),
    CHECK_EVERY_MS,
  );
  window.setTimeout(() => current.settled(), 10_000);

  return () => {
    document.removeEventListener("visibilitychange", onVisibility);
    window.removeEventListener("error", onError);
    window.removeEventListener("unhandledrejection", onRejection);
    pwaSignals?.removeEventListener("outdated", onOutdatedSignal);
    window.clearInterval(hourly);
    window.clearInterval(check);
    manager = null;
  };
}
