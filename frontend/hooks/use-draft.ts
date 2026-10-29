"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useMe } from "@/hooks/use-me";
import { isSupportMode } from "@/lib/auth/support";
import { draftKey, pick, readDraft, removeDraft, writeDraft } from "@/lib/drafts";

export const DRAFT_DELAY_MS = 400;

/** Formulaires dont la saisie n'est pas encore envoyée : un moment n'est pas « sûr » (P2). */
const unsent = new Set<string>();

/** Une saisie vide : chaîne vide, liste vide, absente. Un nombre ou un booléen compte. */
function isBlank(values: Record<string, unknown>, names: readonly string[]): boolean {
  return names.every((name) => {
    const value = values[name];
    if (value === undefined || value === null) return true;
    if (typeof value === "string") return value.trim() === "";
    if (Array.isArray(value)) return value.length === 0;
    if (typeof value === "object") return Object.keys(value).length === 0;
    return false;
  });
}

const NO_KEYS: readonly string[] = [];

export function hasUnsentDrafts(): boolean {
  return unsent.size > 0;
}

export type DraftSpec = {
  /** Nom stable du formulaire (`expense`, `sale-payment`…), figé dans l'ADR 0101. */
  formId: string;
  /** Version du schéma : à monter quand les champs changent de sens. */
  version: number;
  /** Liste blanche : seuls ces champs sont écrits. */
  fields: readonly string[];
  /**
   * Champs qui font un brouillon : si tous sont vides, il n'y en a pas (une catégorie choisie
   * ou la clé d'idempotence seules ne sont pas une saisie). Par défaut : tous.
   */
  meaningful?: readonly string[];
  /** Objet modifié (produit, client…) : un brouillon par objet. */
  objectId?: string;
  /** `false` tant que le formulaire n'est pas prêt (données pas encore chargées). */
  enabled?: boolean;
  /**
   * Champs de clé d'idempotence : écrits avec le brouillon (un envoi interrompu rejoue avec la
   * même clé), mais une clé renouvelée seule n'est pas une saisie — après un envoi réussi, elle
   * ne recrée jamais le brouillon.
   */
  keys?: readonly string[];
  /**
   * Envoi en cours, ou écran « enregistré » : rien n'est écrit (le brouillon d'avant l'envoi
   * reste tel quel, avec la même clé), et un onglet voisin n'écrase rien.
   */
  busy?: boolean;
};

export type Draft = {
  /** Vrai si la saisie affichée vient d'un brouillon retrouvé (bandeau « Brouillon retrouvé »). */
  restored: boolean;
  /** À l'envoi réussi ou sur « Effacer » : le brouillon disparaît. */
  clear: () => void;
};

/**
 * Garde la saisie d'un formulaire (ADR 0101). `values` : l'état courant ; `apply` : remet un
 * brouillon dans le formulaire (une fois à l'ouverture, puis à chaque écriture d'un onglet
 * voisin). Une saisie égale à l'état de départ n'est pas un brouillon.
 */
export function useDraft(
  spec: DraftSpec,
  values: Record<string, unknown>,
  apply: (fields: Record<string, unknown>) => void,
): Draft {
  const {
    formId,
    version,
    fields,
    meaningful = fields,
    objectId,
    enabled = true,
    keys = NO_KEYS,
    busy = false,
  } = spec;
  const me = useMe().data;
  const [restored, setRestored] = useState(false);
  // Au nom de cette personne dans cette entreprise ; jamais en accès support (lecture seule),
  // jamais sans identité complète.
  const companyId = me?.company?.id;
  const userId = me?.user?.id;
  const key =
    companyId && userId && !isSupportMode()
      ? draftKey({ companyId, userId }, formId, objectId)
      : null;
  const initial = useRef<string | null>(null);
  const lastWritten = useRef<string | null>(null);
  // Saisie au moment de `clear()` : jamais réécrite (écran « enregistré », démontage).
  const cleared = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = useRef(values);
  const applyRef = useRef(apply);
  const busyRef = useRef(busy);
  const keyRef = useRef(key);
  // Dernières valeurs lues par les rappels (minuterie, `storage`), mises à jour après rendu.
  useEffect(() => {
    latest.current = values;
    applyRef.current = apply;
    busyRef.current = busy;
    keyRef.current = key;
  });

  const serialize = useCallback(
    (current: Record<string, unknown>) => JSON.stringify(pick(current, fields)),
    // `fields` est une constante du module de chaque formulaire.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  // La saisie sans ses clés : ce qui dit si quelque chose a été tapé.
  const content = useCallback(
    (current: Record<string, unknown>) =>
      JSON.stringify(
        pick(
          current,
          fields.filter((name) => !keys.includes(name)),
        ),
      ),
    // `fields` et `keys` sont des constantes du module de chaque formulaire.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const flush = useCallback(() => {
    if (!key || initial.current === null) return;
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    // Pendant un envoi, le brouillon d'avant reste tel quel : une page qui meurt là rejoue
    // avec la même clé (R1, prompt 32).
    if (busyRef.current) return;
    const snapshot = serialize(latest.current);
    const typed = content(latest.current);
    if (cleared.current !== null) {
      if (typed === cleared.current) return;
      cleared.current = null;
    }
    if (typed === initial.current || isBlank(latest.current, meaningful)) {
      removeDraft(key);
      unsent.delete(key);
      lastWritten.current = null;
      return;
    }
    if (snapshot === lastWritten.current) return;
    writeDraft(key, version, latest.current, fields);
    lastWritten.current = snapshot;
    unsent.add(key);
  }, [key, version, fields, meaningful, serialize, content]);

  // Ouverture : on note l'état de départ, puis on remet le brouillon s'il existe.
  useEffect(() => {
    if (!key || !enabled || initial.current !== null) return;
    initial.current = content(latest.current);
    const found = readDraft(key, version, fields);
    if (found && content(found.fields) !== initial.current && !isBlank(found.fields, meaningful)) {
      applyRef.current(found.fields);
      lastWritten.current = JSON.stringify(found.fields);
      unsent.add(key);
      setRestored(true);
    }
  }, [key, enabled, version, fields, meaningful, content]);

  // L'objet change sous le formulaire (la vente naît au premier article) : le brouillon suit
  // la nouvelle clé, l'ancienne est effacée.
  const previousKey = useRef<string | null>(null);
  useEffect(() => {
    const before = previousKey.current;
    previousKey.current = key;
    if (before && key && before !== key) {
      removeDraft(before);
      unsent.delete(before);
      lastWritten.current = null;
      flush();
    }
  }, [key, flush]);

  // Écriture différée après la dernière frappe (et après un envoi qui n'a pas abouti).
  const snapshot = serialize(values);
  useEffect(() => {
    if (!key || initial.current === null || busy) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(flush, DRAFT_DELAY_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [key, snapshot, busy, flush]);

  // Page cachée (onglet changé, application en arrière-plan, déchargement) : écrit tout de suite.
  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden") flush();
    };
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", flush);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", flush);
      flush();
    };
  }, [flush]);

  // Écran quitté (ou caché par Next) : le brouillon est en stockage et sera retrouvé ; il ne
  // retient plus la mise à jour invisible (R2, prompt 32). Revenu, il la retient de nouveau.
  useEffect(() => {
    if (keyRef.current && lastWritten.current !== null) unsent.add(keyRef.current);
    return () => {
      if (keyRef.current) unsent.delete(keyRef.current);
    };
  }, []);

  // Onglet voisin sur le même formulaire : le dernier qui écrit gagne, sans boucle.
  useEffect(() => {
    if (!key) return;
    const onStorage = (event: StorageEvent) => {
      if (event.key !== key || busyRef.current) return;
      if (event.newValue === null) {
        lastWritten.current = null;
        return;
      }
      const found = readDraft(key, version, fields);
      if (!found) return;
      const incoming = JSON.stringify(found.fields);
      if (incoming === lastWritten.current) return;
      lastWritten.current = incoming;
      applyRef.current(found.fields);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [key, version, fields]);

  const clear = useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    if (key) {
      removeDraft(key);
      unsent.delete(key);
    }
    cleared.current = content(latest.current);
    lastWritten.current = null;
    setRestored(false);
  }, [key, content]);

  return { restored, clear };
}
