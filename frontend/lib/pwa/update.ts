/**
 * Mise à jour invisible de l'application installée (prompt 29, P2, ADR 0102).
 *
 * Le nouveau service worker se prépare en arrière-plan puis **attend**. Il n'est activé — et la
 * page rechargée — qu'à un moment sûr :
 * - au lancement de l'application ;
 * - au retour d'un passage en arrière-plan de plus de 5 minutes ;
 * - à la navigation suivante entre deux écrans par un lien ;
 * - après 24 heures d'attente sur un même écran ;
 * et seulement si aucune écriture n'est en cours et qu'aucune saisie n'attend d'être envoyée
 * (brouillon, encaissement). Jamais pendant une vente ou une saisie. Aucune bannière, sauf en
 * dernier recours : le serveur refuse encore la version après une mise à jour (426).
 */

export const BACKGROUND_MS = 5 * 60 * 1000;
export const IDLE_MS = 24 * 60 * 60 * 1000;
export const CHECK_EVERY_MS = 6 * 60 * 60 * 1000;

const RELOADED_FOR_OUTDATED = "coges:pwa:reloaded-outdated";
const RELOADED_FOR_CHUNK = "coges:pwa:reloaded-chunk";

export type Trigger = "launch" | "foreground" | "navigation" | "idle" | "outdated" | "chunk";

export type UpdateDeps = {
  /** Écritures en cours (TanStack Query `isMutating`). */
  pendingWrites: () => number;
  /** Une saisie n'est pas envoyée (`hasUnsentDrafts`). */
  unsentInput: () => boolean;
  /** Active le worker en attente ; résout quand la page peut être rechargée. */
  activateWaiting: () => Promise<boolean>;
  reload: () => void;
  now: () => number;
  session: Pick<Storage, "getItem" | "setItem" | "removeItem"> | null;
  /** Dernier recours : demande à la page d'afficher « Une nouvelle version est prête ». */
  showOutdated: () => void;
};

export function isSafeMoment(deps: Pick<UpdateDeps, "pendingWrites" | "unsentInput">): boolean {
  return deps.pendingWrites() === 0 && !deps.unsentInput();
}

export class UpdateManager {
  private waitingSince: number | null = null;
  private hiddenAt: number | null = null;
  /** Rechargement voulu sans worker en attente (fichier manquant, version refusée). */
  private reloadWanted: Trigger | null = null;
  private busy = false;

  constructor(private readonly deps: UpdateDeps) {}

  /** Un nouveau worker attend (installé, pas encore actif). */
  workerWaiting(): void {
    this.waitingSince ??= this.deps.now();
  }

  hasWaiting(): boolean {
    return this.waitingSince !== null;
  }

  pageHidden(): void {
    this.hiddenAt = this.deps.now();
  }

  /** Retour au premier plan : un moment sûr seulement après plus de 5 minutes d'absence. */
  pageVisible(): Promise<boolean> {
    const away = this.hiddenAt === null ? 0 : this.deps.now() - this.hiddenAt;
    this.hiddenAt = null;
    return away > BACKGROUND_MS ? this.consider("foreground") : Promise.resolve(false);
  }

  /** Appelé à chaque changement d'écran par un lien, et à chaque heure (pour les 24 h). */
  consider(trigger: Trigger): Promise<boolean> {
    if (trigger === "idle") {
      const waited = this.waitingSince === null ? 0 : this.deps.now() - this.waitingSince;
      if (waited < IDLE_MS && this.reloadWanted === null) return Promise.resolve(false);
    }
    if (!this.hasWaiting() && this.reloadWanted === null) return Promise.resolve(false);
    if (this.busy || !isSafeMoment(this.deps)) return Promise.resolve(false);
    return this.apply();
  }

  /** Le serveur refuse cette version (426 `front_outdated`). */
  outdated(): Promise<boolean> {
    // Déjà rechargé pour cette raison et toujours refusé : seul le dernier recours reste.
    if (this.deps.session?.getItem(RELOADED_FOR_OUTDATED)) {
      this.deps.showOutdated();
      return Promise.resolve(false);
    }
    this.reloadWanted = "outdated";
    return this.consider("outdated");
  }

  /** Un fichier de l'application n'a pas pu être chargé : un seul rechargement propre. */
  chunkFailed(): Promise<boolean> {
    if (this.deps.session?.getItem(RELOADED_FOR_CHUNK)) return Promise.resolve(false);
    this.reloadWanted = "chunk";
    return this.consider("chunk");
  }

  /** Une page servie normalement : les drapeaux de rechargement peuvent tomber. */
  settled(): void {
    this.deps.session?.removeItem(RELOADED_FOR_CHUNK);
  }

  private async apply(): Promise<boolean> {
    this.busy = true;
    try {
      if (this.reloadWanted === "outdated") this.deps.session?.setItem(RELOADED_FOR_OUTDATED, "1");
      if (this.reloadWanted === "chunk") this.deps.session?.setItem(RELOADED_FOR_CHUNK, "1");
      if (this.hasWaiting()) {
        const ready = await this.deps.activateWaiting();
        if (!ready) return false;
      }
      this.deps.reload();
      return true;
    } finally {
      this.busy = false;
    }
  }
}

/** Reconnaît l'échec de chargement d'un fichier de l'application (anciens fichiers retirés). */
export function isChunkLoadError(reason: unknown): boolean {
  const text =
    reason instanceof Error
      ? `${reason.name} ${reason.message}`
      : typeof reason === "string"
        ? reason
        : "";
  return /ChunkLoadError|Loading chunk [\w-]+ failed|Failed to fetch dynamically imported module|Importing a module script failed/i.test(
    text,
  );
}

export function outdatedFlagCleared(session: UpdateDeps["session"]): void {
  session?.removeItem(RELOADED_FOR_OUTDATED);
}
