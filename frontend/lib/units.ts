import { formatQtyWithUnit } from "@/lib/format";
import { labels } from "@/lib/labels";

type Unit = keyof typeof labels.units;

/** « 2 sacs », « 1 bouteille », « 40 kg » : la quantité et son unité accordée. */
export function qtyWithUnit(value: string, unit: string): string {
  if (!(unit in labels.units)) return `${formatQtyWithUnit(value, unit, unit)}`;
  const known = unit as Unit;
  return formatQtyWithUnit(value, labels.units[known], labels.unitsPlural[known]);
}

/**
 * Numéro d'une pièce tel que la maquette v2 le montre : « Vente n° 1044 » pour V-001044. Le
 * numéro complet reste celui de l'API, des exports et de la recherche (qui accepte les deux).
 */
export function displayNumber(documentNo: string): string {
  const match = /^[A-Z]+-0*(\d+)$/.exec(documentNo);
  return match?.[1] ?? documentNo;
}
