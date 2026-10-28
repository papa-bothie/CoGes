import { describe, expect, it, vi } from "vitest";

import { BACKGROUND_MS, IDLE_MS, isChunkLoadError, UpdateManager, type UpdateDeps } from "./update";

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
});
