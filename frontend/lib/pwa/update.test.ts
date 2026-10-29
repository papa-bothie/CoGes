import { describe, expect, it, vi } from "vitest";

import {
  BACKGROUND_MS,
  IDLE_MS,
  isChunkLoadError,
  OUTDATED_PATIENCE_MS,
  OUTDATED_REFUSALS,
  reloadOnceForChunk,
  UpdateManager,
  type UpdateDeps,
} from "./update";

function setup(overrides: Partial<UpdateDeps> = {}) {
  let clock = 1_000_000;
  const store = new Map<string, string>();
  const state = { writes: 0, unsent: false };
  const deps: UpdateDeps = {
    pendingWrites: () => state.writes,
    unsentInput: () => state.unsent,
    activateWaiting: vi.fn(async () => true),
    reload: vi.fn(),
    now: () => clock,
    session: {
      getItem: (key) => store.get(key) ?? null,
      setItem: (key, value) => void store.set(key, value),
      removeItem: (key) => void store.delete(key),
    },
    showOutdated: vi.fn(),
    ...overrides,
  };
  const manager = new UpdateManager(deps);
  return { manager, deps, state, tick: (ms: number) => (clock += ms) };
}

describe("mise à jour invisible (ADR 0102)", () => {
  it("rien à faire sans nouvelle version", async () => {
    const { manager, deps } = setup();
    expect(await manager.consider("navigation")).toBe(false);
    expect(deps.reload).not.toHaveBeenCalled();
  });

  it("au lancement, la version en attente s'active", async () => {
    const { manager, deps } = setup();
    manager.workerWaiting();
    expect(await manager.consider("launch")).toBe(true);
    expect(deps.activateWaiting).toHaveBeenCalledOnce();
    expect(deps.reload).toHaveBeenCalledOnce();
  });

  it("jamais pendant une écriture ni avec une saisie non envoyée", async () => {
    const { manager, deps, state } = setup();
    manager.workerWaiting();
    state.writes = 1;
    expect(await manager.consider("navigation")).toBe(false);
    state.writes = 0;
    state.unsent = true;
    expect(await manager.consider("navigation")).toBe(false);
    expect(deps.reload).not.toHaveBeenCalled();
    // La vente envoyée, le brouillon effacé : la navigation suivante est un moment sûr.
    state.unsent = false;
    expect(await manager.consider("navigation")).toBe(true);
  });

  it("au retour d'arrière-plan : seulement après plus de 5 minutes", async () => {
    const { manager, deps, tick } = setup();
    manager.workerWaiting();
    manager.pageHidden();
    tick(BACKGROUND_MS - 1);
    expect(await manager.pageVisible()).toBe(false);
    manager.pageHidden();
    tick(BACKGROUND_MS + 1);
    expect(await manager.pageVisible()).toBe(true);
    expect(deps.reload).toHaveBeenCalledOnce();
  });

  it("sur un même écran : après 24 heures d'attente, pas avant", async () => {
    const { manager, tick } = setup();
    manager.workerWaiting();
    tick(IDLE_MS - 1);
    expect(await manager.consider("idle")).toBe(false);
    tick(2);
    expect(await manager.consider("idle")).toBe(true);
  });

  it("version refusée par le serveur : rechargée une fois au moment sûr, puis la bannière", async () => {
    const { manager, deps, state } = setup();
    state.unsent = true;
    expect(await manager.outdated()).toBe(false);
    expect(deps.reload).not.toHaveBeenCalled();
    state.unsent = false;
    expect(await manager.consider("navigation")).toBe(true);
    expect(deps.reload).toHaveBeenCalledOnce();
    // Après le rechargement, toujours refusée : dernier recours, la bannière.
    const again = new UpdateManager(deps);
    expect(await again.outdated()).toBe(false);
    expect(deps.showOutdated).toHaveBeenCalledOnce();
  });

  it("fichier de l'application manquant : un seul rechargement propre", async () => {
    const { manager, deps } = setup();
    expect(await manager.chunkFailed()).toBe(true);
    const next = new UpdateManager(deps);
    expect(await next.chunkFailed()).toBe(false);
    expect(deps.reload).toHaveBeenCalledOnce();
  });

  it("reconnaît un fichier de l'application introuvable", () => {
    const error = new Error("Loading chunk 123 failed.");
    error.name = "ChunkLoadError";
    expect(isChunkLoadError(error)).toBe(true);
    expect(isChunkLoadError(new TypeError("Failed to fetch dynamically imported module: x"))).toBe(
      true,
    );
    expect(isChunkLoadError(new Error("insufficient_stock"))).toBe(false);
  });

  it("deux onglets : celui qui n'a pas activé la version recharge au moment sûr suivant", async () => {
    // Un seul worker en attente pour les deux onglets ; l'activer change le contrôleur des deux.
    const shared = { waiting: true };
    const tabs: ReturnType<typeof setup>[] = [];
    const activate = vi.fn(async () => {
      if (!shared.waiting) return false;
      shared.waiting = false;
      for (const tab of tabs) tab.manager.controllerChanged();
      return true;
    });
    const a = setup({ activateWaiting: activate });
    const b = setup({ activateWaiting: activate });
    tabs.push(a, b);
    a.manager.workerWaiting();
    b.manager.workerWaiting();
    b.state.unsent = true;
    expect(await a.manager.consider("navigation")).toBe(true);
    expect(await b.manager.consider("navigation")).toBe(false);
    b.state.unsent = false;
    expect(await b.manager.consider("navigation")).toBe(true);
    expect(b.deps.reload).toHaveBeenCalledOnce();
  });

  it("le drapeau de rechargement n'est posé qu'au rechargement effectif", async () => {
    const { manager, deps } = setup({ activateWaiting: vi.fn(async () => false) });
    manager.workerWaiting();
    expect(await manager.chunkFailed()).toBe(false);
    expect(deps.reload).not.toHaveBeenCalled();
    // La page suivante réessaie : aucun drapeau n'a été laissé par l'échec.
    const next = new UpdateManager({ ...deps, activateWaiting: vi.fn(async () => true) });
    next.workerWaiting();
    expect(await next.chunkFailed()).toBe(true);
    expect(deps.reload).toHaveBeenCalledOnce();
  });

  it("426 sans moment sûr : la bannière après plusieurs refus, sans recharger d'office", async () => {
    const { manager, deps, state } = setup();
    state.unsent = true;
    for (let refusal = 1; refusal < OUTDATED_REFUSALS; refusal += 1) await manager.outdated();
    expect(deps.showOutdated).not.toHaveBeenCalled();
    await manager.outdated();
    expect(deps.showOutdated).toHaveBeenCalledOnce();
    expect(deps.reload).not.toHaveBeenCalled();
  });

  it("426 sans moment sûr : la bannière après quelques minutes, même sur un seul refus de plus", async () => {
    const { manager, deps, state, tick } = setup();
    state.unsent = true;
    await manager.outdated();
    tick(OUTDATED_PATIENCE_MS + 1);
    await manager.outdated();
    expect(deps.showOutdated).toHaveBeenCalledOnce();
    expect(deps.reload).not.toHaveBeenCalled();
  });

  it("le moment sûr est revérifié juste avant de recharger", async () => {
    const { manager, deps, state } = setup({
      activateWaiting: vi.fn(async () => {
        // Pendant l'attente de l'activation, la personne commence une vente.
        state.unsent = true;
        return true;
      }),
    });
    manager.workerWaiting();
    expect(await manager.consider("navigation")).toBe(false);
    expect(deps.reload).not.toHaveBeenCalled();
    state.unsent = false;
    expect(await manager.consider("navigation")).toBe(true);
    // La version est déjà active : on recharge sans la réactiver.
    expect(deps.activateWaiting).toHaveBeenCalledOnce();
  });

  it("un rechargement lancé n'est pas relancé par la navigation qui suit", async () => {
    const { manager, deps } = setup();
    expect(await manager.chunkFailed()).toBe(true);
    expect(await manager.consider("navigation")).toBe(false);
    expect(deps.reload).toHaveBeenCalledOnce();
  });

  it("reconnaît l'échec de chargement de Turbopack, même sous forme de texte ou de cause", () => {
    const message =
      "Failed to load chunk /_next/static/chunks/0abc123.js from module 4567: Error: 404";
    expect(isChunkLoadError(message)).toBe(true);
    expect(isChunkLoadError({ name: "ChunkLoadError", message })).toBe(true);
    expect(isChunkLoadError(new Error("rendu interrompu", { cause: new Error(message) }))).toBe(
      true,
    );
  });
});

describe("sans gestionnaire", () => {
  it("un seul rechargement par session pour un fichier manquant", () => {
    const store = new Map<string, string>();
    const session = {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
    };
    const reload = vi.fn();
    expect(reloadOnceForChunk(session, reload)).toBe(true);
    expect(reloadOnceForChunk(session, reload)).toBe(false);
    expect(reload).toHaveBeenCalledOnce();
  });
});
