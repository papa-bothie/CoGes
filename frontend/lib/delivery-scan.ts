import { addDecimal, compareDecimal, parseDecimalInput } from "@/lib/decimal";
import { formatQty } from "@/lib/format";
import type { Schemas } from "@/lib/api/schema";

/**
 * Entrée de stock par scan (prompt 33, ADR 0106) : ce que l'écran « Recevoir une
 * livraison » fait d'un article lu, sans composant React pour être testé seul.
 */

/** Ce qu'une ligne de livraison sait de son article : assez pour l'afficher et l'envoyer. */
export type LineProduct = {
  product_id: string;
  name: string;
  unit: Schemas["ProductUnit"];
  qty_on_hand: string;
};
export type DeliveryLine = { product: LineProduct; qty: string; cost: string };

/** Le code tel que l'API le cherche : aucun espace, nulle part (le serveur vérifie la clé). */
export function cleanScannedCode(raw: string): string {
  return raw.replace(/\s+/g, "");
}

/**
 * Un article scanné : une nouvelle ligne d'une pièce au dernier prix d'achat, ou, s'il est
 * déjà sur la livraison, une pièce de plus sur sa ligne (jamais de doublon : le serveur
 * refuse deux lignes du même article).
 */
export function addScannedLine(
  lines: readonly DeliveryLine[],
  product: LineProduct,
  cost: string,
): { lines: DeliveryLine[]; merged: boolean } {
  const index = lines.findIndex((line) => line.product.product_id === product.product_id);
  if (index === -1) return { lines: [...lines, { product, qty: "1", cost }], merged: false };
  return {
    merged: true,
    lines: lines.map((line, i) => {
      if (i !== index) return line;
      const qty = parseDecimalInput(line.qty) ?? "0";
      return { ...line, qty: addDecimal(qty, "1") ?? "1" };
    }),
  };
}

/** « Riz 25 kg : 5 → 25 » pour chaque ligne qui a une quantité : l'effet exact de la validation. */
export function stockEffects(lines: readonly DeliveryLine[]): string[] {
  return lines.flatMap((line) => {
    const qty = parseDecimalInput(line.qty);
    if (qty === null || compareDecimal(qty, "0") !== 1) return [];
    const after = addDecimal(line.product.qty_on_hand, qty);
    if (after === null) return [];
    return [`${line.product.name} : ${formatQty(line.product.qty_on_hand)} → ${formatQty(after)}`];
  });
}
