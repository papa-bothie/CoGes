/**
 * Montants tapés librement (règle de saisie libre du lot 1, phase 15) : raccourcis,
 * monnaie à rendre et message sous le champ, repris des formules de la maquette v2
 * (`Reglement`, `PayerFournisseur`, `Vente`). Les montants sont des entiers (XOF n'a pas
 * de décimales) manipulés en `bigint` : jamais de flottant sur de l'argent.
 */
import { formatAmount } from "@/lib/format/money";
import { labels } from "@/lib/labels";

/** Partie entière d'un montant de l'API (« 25000.00 » → 25000n), 0 si vide. */
export function wholeUnits(value: string | null | undefined): bigint {
  const integer = (value ?? "").trim().split(".")[0]?.replace(/\D/g, "") ?? "";
  return integer ? BigInt(integer) : 0n;
}

/** Montant tapé (chiffres seuls) en `bigint`. */
export function typedAmount(typed: string): bigint {
  return typed ? BigInt(typed) : 0n;
}

function money(value: bigint, currency: string): string {
  return formatAmount(value.toString(), currency);
}

/** Arrondi au multiple de 500 le plus proche, comme la maquette (`Math.round(x / 500) * 500`). */
function roundTo500(value: bigint): bigint {
  return ((value + 250n) / 500n) * 500n;
}

export type Shortcut = { label: string; value: string };

function unique(values: bigint[], keep: (value: bigint) => boolean): bigint[] {
  return values.filter((value, index) => keep(value) && values.indexOf(value) === index);
}

/** « Tout : 25 000 F », « La moitié : 12 500 F », « 5 000 F » (encaisser, payer). */
export function debtShortcuts(due: bigint, currency: string): Shortcut[] {
  const values = unique([due, roundTo500(due / 2n), 5000n], (v) => v > 0n && v <= due);
  return values.map((value, index) => ({
    value: value.toString(),
    label:
      index === 0
        ? labels.payment.all(money(value, currency))
        : index === 1 && value === roundTo500(due / 2n)
          ? labels.payment.half(money(value, currency))
          : money(value, currency),
  }));
}

/** Vente payée en partie : la moitié puis le quart, arrondis à 500. */
export function partShortcuts(total: bigint, currency: string): Shortcut[] {
  const values = unique([roundTo500(total / 2n), roundTo500(total / 4n)], (v) => v > 0n);
  return values.map((value, index) => ({
    value: value.toString(),
    label: index === 0 ? labels.payment.half(money(value, currency)) : money(value, currency),
  }));
}

/** « Le compte juste », puis les billets au-dessus du total (10 000, 20 000, 50 000). */
export function billShortcuts(total: bigint, currency: string): Shortcut[] {
  const values = unique([total, 10000n, 20000n, 50000n], (v) => v > 0n && v >= total);
  return values.map((value) => ({
    value: value.toString(),
    label: value === total ? labels.payment.exact : money(value, currency),
  }));
}

/** Monnaie à rendre, ou `null` si le client ne donne pas plus que le total. */
export function changeDue(given: bigint, total: bigint): bigint | null {
  return given > total ? given - total : null;
}

export type Check = { ok: boolean; tone: "attente" | "bon" | "trop"; message: string };

/**
 * Encaisser une dette (`client`), payer un fournisseur (`fournisseur`) ou rendre l'argent
 * d'un retour (`remboursement`) : de 1 F jusqu'au total dû. Le message suit la maquette.
 */
export function debtPaymentCheck(
  typed: string,
  due: bigint,
  payer: "client" | "fournisseur" | "remboursement",
  currency: string,
): Check {
  const amount = typedAmount(typed);
  const t = labels.payment[payer];
  if (amount === 0n) return { ok: false, tone: "attente", message: t.empty };
  if (amount > due) return { ok: false, tone: "trop", message: t.tooMuch(money(due, currency)) };
  if (amount === due) return { ok: true, tone: "bon", message: t.cleared };
  return {
    ok: true,
    tone: "bon",
    message: labels.payment.remaining(money(due - amount, currency)),
  };
}

/** Vente payée en partie : de 1 F jusqu'au total exclu (le total, c'est « Tout payé »). */
export function partPaymentCheck(typed: string, total: bigint, currency: string): Check {
  const amount = typedAmount(typed);
  if (amount === 0n) return { ok: false, tone: "attente", message: labels.payment.sale.empty };
  if (amount >= total) return { ok: false, tone: "trop", message: labels.payment.sale.tooMuch };
  return {
    ok: true,
    tone: "bon",
    message: labels.payment.remaining(money(total - amount, currency)),
  };
}
