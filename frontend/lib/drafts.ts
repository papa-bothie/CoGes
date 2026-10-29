/**
 * Brouillons de saisie (prompt 29, P1, ADR 0101) : ce qu'une personne a commencé à taper
 * se retrouve après un changement d'écran, un rechargement ou un déchargement de la page.
 *
 * Règles de sécurité — ce qui reste sur l'appareil ne doit jamais trahir la boutique :
 * - une clé par entreprise **et** par personne (`coges:draft:v1:<entreprise>:<personne>:…`) :
 *   personne d'autre ne relit un brouillon, même sur le même navigateur ;
 * - une **liste blanche** de champs par formulaire : rien d'autre n'est écrit (jamais un mot
 *   de passe, un code ou une référence de paiement) ;
 * - 24 heures sans modification, puis effacé ; effacé aussi à l'envoi, à « Effacer », à la
 *   déconnexion et à l'expiration de session ;
 * - une version de formulaire inconnue est ignorée, jamais appliquée.
 *
 * Tout accès au stockage est sous `try/catch` : absent, plein ou bloqué, l'écran marche sans.
 */

export const DRAFT_PREFIX = "coges:draft:v1:";
export const DRAFT_TTL_MS = 24 * 60 * 60 * 1000;

export type DraftOwner = { companyId: string; userId: string };

type Stored = { v: number; at: number; fields: Record<string, unknown> };

/**
 * Dernier propriétaire, gardé sur l'appareil (deux identifiants, rien d'autre) : une session
 * expirée à la réouverture, avant que `/auth/me` réponde, efface quand même ses brouillons.
 */
export const DRAFT_OWNER_KEY = "coges:draft-owner";

let owner: DraftOwner | null = null;
// Posé par la déconnexion avant toute redirection : plus aucune écriture (page cachée,
// démontage) ne recrée un brouillon que l'on vient d'effacer.
let frozen = false;

/** Posée par la coquille dès que l'identité est connue ; `null` hors session. */
export function setDraftOwner(next: DraftOwner | null): void {
  owner = next;
  if (!next) return;
  frozen = false;
  try {
    storage()?.setItem(DRAFT_OWNER_KEY, JSON.stringify(next));
  } catch {
    // Sans stockage, il n'y a pas de brouillon à effacer non plus.
  }
}

/** Signal de déconnexion : plus aucune écriture jusqu'à la personne suivante. */
export function freezeDrafts(): void {
  frozen = true;
}

function rememberedOwner(): DraftOwner | null {
  try {
    const parsed = JSON.parse(storage()?.getItem(DRAFT_OWNER_KEY) ?? "null") as unknown;
    if (!parsed || typeof parsed !== "object") return null;
    const { companyId, userId } = parsed as Partial<DraftOwner>;
    return typeof companyId === "string" && typeof userId === "string"
      ? { companyId, userId }
      : null;
  } catch {
    return null;
  }
}

export function draftOwner(): DraftOwner | null {
  return owner;
}

export function draftKey(who: DraftOwner, formId: string, objectId?: string): string {
  return `${DRAFT_PREFIX}${who.companyId}:${who.userId}:${formId}${objectId ? `:${objectId}` : ""}`;
}

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/** Ne garde que les champs de la liste blanche, et seulement des valeurs simples. */
export function pick(
  values: Record<string, unknown>,
  allowed: readonly string[],
): Record<string, unknown> {
  const kept: Record<string, unknown> = {};
  for (const name of allowed) {
    const value = values[name];
    if (value === undefined) continue;
    kept[name] = value;
  }
  return kept;
}

export function readDraft(
  key: string,
  version: number,
  allowed: readonly string[],
  now = Date.now(),
): { fields: Record<string, unknown>; at: number } | null {
  const store = storage();
  if (!store) return null;
  try {
    const raw = store.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Stored>;
    if (parsed.v !== version || typeof parsed.at !== "number" || !parsed.fields) {
      // Version inconnue : ignorée, et retirée pour ne pas la relire à chaque visite.
      store.removeItem(key);
      return null;
    }
    if (now - parsed.at > DRAFT_TTL_MS) {
      store.removeItem(key);
      return null;
    }
    return { fields: pick(parsed.fields, allowed), at: parsed.at };
  } catch {
    return null;
  }
}

export function writeDraft(
  key: string,
  version: number,
  values: Record<string, unknown>,
  allowed: readonly string[],
  now = Date.now(),
): void {
  const store = storage();
  if (!store || frozen) return;
  try {
    const stored: Stored = { v: version, at: now, fields: pick(values, allowed) };
    store.setItem(key, JSON.stringify(stored));
  } catch {
    // Stockage plein ou refusé : la saisie reste à l'écran, rien de plus.
  }
}

export function removeDraft(key: string): void {
  try {
    storage()?.removeItem(key);
  } catch {
    // Rien à faire : le brouillon expirera.
  }
}

function keys(): string[] {
  const store = storage();
  if (!store) return [];
  try {
    const found: string[] = [];
    for (let index = 0; index < store.length; index += 1) {
      const key = store.key(index);
      if (key?.startsWith(DRAFT_PREFIX)) found.push(key);
    }
    return found;
  } catch {
    return [];
  }
}

/** Efface tous les brouillons d'une personne (déconnexion, expiration de session). */
export function clearDraftsOf(who: DraftOwner): void {
  const prefix = `${DRAFT_PREFIX}${who.companyId}:${who.userId}:`;
  for (const key of keys()) if (key.startsWith(prefix)) removeDraft(key);
}

/**
 * Efface les brouillons de la personne courante — ou, avant que son identité soit relue, du
 * dernier propriétaire gardé — puis l'oublie.
 */
export function clearOwnDrafts(): void {
  const who = owner ?? rememberedOwner();
  if (who) clearDraftsOf(who);
  owner = null;
  removeDraft(DRAFT_OWNER_KEY);
}

/** Nettoyage au démarrage : tout brouillon de plus de 24 h ou illisible disparaît. */
export function purgeExpiredDrafts(now = Date.now()): void {
  const store = storage();
  if (!store) return;
  for (const key of keys()) {
    try {
      const parsed = JSON.parse(store.getItem(key) ?? "") as Partial<Stored>;
      if (typeof parsed.at !== "number" || now - parsed.at > DRAFT_TTL_MS) removeDraft(key);
    } catch {
      removeDraft(key);
    }
  }
}

/* Lecture prudente d'un brouillon : une valeur qui n'a pas la forme attendue est ignorée. */

export function draftString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

export function draftOneOf<T extends string>(value: unknown, allowed: readonly T[]): T | undefined {
  return typeof value === "string" && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : undefined;
}

/** Le choix « Aujourd'hui / Hier / Autre jour » des écrans d'argent (`components/kit/when-chips`). */
export function draftWhen(
  value: unknown,
): { kind: "today" | "yesterday" | "other"; day: string } | undefined {
  if (!value || typeof value !== "object") return undefined;
  const { kind, day } = value as { kind?: unknown; day?: unknown };
  const parsedKind = draftOneOf(kind, ["today", "yesterday", "other"] as const);
  return parsedKind && typeof day === "string" ? { kind: parsedKind, day } : undefined;
}
