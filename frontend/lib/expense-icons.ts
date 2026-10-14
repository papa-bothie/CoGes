import {
  Droplet,
  Ellipsis,
  House,
  Receipt,
  Smartphone,
  Truck,
  User,
  Wrench,
  Zap,
  type LucideIcon,
} from "lucide-react";

/**
 * Icône d'un type de dépense (maquette 20), **déduite de son nom** : les catégories n'ont
 * pas de colonne d'icône (ADR 0073). Un nom inattendu reçoit « … ».
 */
const RULES: readonly [RegExp, LucideIcon][] = [
  [/loyer|bail|location/, House],
  [/[ée]lectricit|courant|senelec|lumi[eè]re/, Zap],
  [/\beau\b|sen.?eau|sde\b/, Droplet],
  [/transport|taxi|carburant|essence|livraison|voiture/, Truck],
  [/salaire|paie|employ|personnel/, User],
  [/t[ée]l[ée]phone|internet|cr[ée]dit|forfait|wifi/, Smartphone],
  [/r[ée]paration|entretien|travaux|maintenance/, Wrench],
  [/taxe|imp[oô]t|patente|douane|tva/, Receipt],
];

export function expenseIcon(name: string): LucideIcon {
  const key = name.toLocaleLowerCase("fr-FR");
  return RULES.find(([pattern]) => pattern.test(key))?.[1] ?? Ellipsis;
}
