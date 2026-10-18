import { compareDecimal, subtractDecimal } from "./decimal";

/**
 * **Préremplissage** d'un règlement réparti sur plusieurs dettes (ADR 0055) : le montant
 * saisi couvre les dettes dans l'ordre donné (la plus ancienne échéance d'abord), chacune
 * à hauteur de son solde. Ce n'est qu'une proposition modifiable : le serveur refuse une
 * affectation au-delà du solde (409) ou du versement (422), et c'est lui qui fait foi.
 */
export function splitAcrossDebts(
  amount: string,
  debts: readonly { id: string; balance: string }[],
): Record<string, string> {
  const result: Record<string, string> = {};
  let remaining = amount;
  for (const debt of debts) {
    if (compareDecimal(remaining, "0") !== 1) break;
    // Une dette sans solde (déjà réglée, ou négative par erreur) ne reçoit rien (ADR 0088).
    if (compareDecimal(debt.balance, "0") !== 1) continue;
    const takesAll = compareDecimal(remaining, debt.balance) !== -1;
    const share = takesAll ? debt.balance : remaining;
    result[debt.id] = share;
    remaining = subtractDecimal(remaining, share) ?? "0";
  }
  return result;
}
