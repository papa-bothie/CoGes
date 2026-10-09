import { describe, expect, it } from "vitest";

import { labels } from "./labels";
import { METRIC_TEXTS } from "./metrics";

/**
 * Lexique du lot 2 de la phase 15 (« Mots simples ») : aucun terme de gestionnaire dans
 * les textes affichés. Chaque terme interdit a son remplaçant entre parenthèses.
 */
const FORBIDDEN: { term: string; pattern: RegExp }[] = [
  { term: "CA (Ventes, Vendu)", pattern: /\bCA\b/ },
  { term: "chiffre d'affaires (Ventes, Vendu)", pattern: /chiffre d['’]affaires/i },
  { term: "CMP (Prix d'achat moyen, Valeur du stock)", pattern: /\bCMP\b/ },
  { term: "coût moyen pondéré (Prix d'achat moyen)", pattern: /pond[ée]r/i },
  { term: "coût des ventes (Prix d'achat des articles vendus)", pattern: /co[uû]t des ventes/i },
  { term: "marge (Gagné sur les ventes)", pattern: /\bmarges?\b/i },
  { term: "résultat estimé (Gagné, Perdu)", pattern: /r[ée]sultat estim/i },
  { term: "encaissement (Entré dans la caisse)", pattern: /\bencaissements?\b/i },
  { term: "décaissement (Sorti de la caisse)", pattern: /\bd[ée]caissements?\b/i },
  { term: "trésorerie (Différence, caisse)", pattern: /tr[ée]sorerie/i },
  { term: "créance (Les clients vous doivent)", pattern: /cr[ée]ances?/i },
  { term: "dettes fournisseurs (Vous devez aux fournisseurs)", pattern: /dettes fournisseurs/i },
  { term: "SKU (Référence)", pattern: /\bSKU\b/i },
  { term: "N° (Vente n°, Retour n°, Dépense n°)", pattern: /(^|[^\p{L}])N°/u },
  { term: "motif (Pourquoi ?)", pattern: /\bmotifs?\b/i },
  { term: "mouvement de stock manuel (Corriger le stock)", pattern: /mouvement de stock manuel/i },
  { term: "échéance (À payer avant le)", pattern: /[ée]ch[ée]ances?/i },
  { term: "client anonyme (Client de passage)", pattern: /anonyme/i },
  { term: "explication d'un calcul", pattern: /toutes périodes confondues/i },
];

/**
 * Exceptions, chacune justifiée. Clé : chemin dans `labels` (ou `metrics.<métrique>`).
 * - `labels.receipt.invoiceNo` : « N° F-1044 » sous « FACTURE », mot pour mot de la
 *   maquette v2 (05b) ; le titre dit déjà de quelle pièce il s'agit.
 */
const EXCEPTIONS = new Set<string>(["labels.receipt.invoiceNo"]);

/** Chaque texte, avec son chemin ; une fonction est appelée avec des valeurs factices. */
function texts(value: unknown, path: string): { path: string; text: string }[] {
  if (typeof value === "string") return [{ path, text: value }];
  if (typeof value === "function") {
    try {
      const out: unknown = (value as (...args: unknown[]) => unknown)("Produit A", 1, 2, "3");
      return typeof out === "string" ? [{ path, text: out }] : [];
    } catch {
      return [];
    }
  }
  if (value && typeof value === "object") {
    return Object.entries(value).flatMap(([key, child]) => texts(child, `${path}.${key}`));
  }
  return [];
}

describe("mots simples (lot 2)", () => {
  it("aucun terme de gestionnaire dans les textes affichés", () => {
    const all = [...texts(labels, "labels"), ...texts(METRIC_TEXTS, "metrics")];
    const found = all.flatMap(({ path, text }) =>
      EXCEPTIONS.has(path)
        ? []
        : FORBIDDEN.filter(({ pattern }) => pattern.test(text)).map(
            ({ term }) => `${path} : « ${text} » → ${term}`,
          ),
    );
    expect(found).toEqual([]);
  });

  it("le test attrape bien un ancien terme", () => {
    const sample = texts({ a: "CA du jour", b: (n: string) => `Motif : ${n}` }, "x");
    const caught = sample.filter(({ text }) => FORBIDDEN.some(({ pattern }) => pattern.test(text)));
    expect(caught).toHaveLength(2);
  });
});
