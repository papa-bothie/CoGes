/**
 * Noms lisibles du catalogue de permissions (`ressource:action`, ADR 0007) et des tables
 * du journal. Un code inconnu s'affiche tel quel : l'écran ne cache jamais un droit.
 */

export const RESOURCE_LABELS: Record<string, string> = {
  analytics: "Analytics",
  audit: "Journal d'activité",
  categories: "Catégories",
  company: "Entreprise",
  customers: "Clients",
  dashboard: "Tableau de bord",
  debts: "Dettes",
  expenses: "Dépenses",
  importexport: "Import / export",
  insights: "CoGes Intelligence",
  inventory: "Stock",
  notifications: "Notifications",
  payments: "Paiements",
  prices: "Prix",
  products: "Produits",
  roles: "Rôles",
  sale_returns: "Retours",
  sales: "Ventes",
  suppliers: "Fournisseurs",
  system: "Santé du système",
  users: "Utilisateurs",
};

export const ACTION_LABELS: Record<string, string> = {
  read: "consulter",
  create: "créer",
  update: "modifier",
  delete: "supprimer",
  confirm: "confirmer",
  cancel: "annuler",
  export: "exporter",
  write_off: "abandonner",
};

export function resourceLabel(resource: string): string {
  return RESOURCE_LABELS[resource] ?? resource;
}

/** Tables tracées dans `audit_logs`, dans l'ordre du filtre. */
export const AUDIT_ENTITIES: Record<string, string> = {
  sales: "Ventes",
  sale_returns: "Retours",
  payments: "Paiements",
  debts: "Dettes",
  expenses: "Dépenses",
  inventory_movements: "Mouvements de stock",
  product_prices: "Prix",
  products: "Produits",
  customers: "Clients",
  suppliers: "Fournisseurs",
  categories: "Catégories",
  companies: "Entreprise",
  users: "Utilisateurs",
  user_roles: "Rôles des utilisateurs",
  roles: "Rôles",
  auth_sessions: "Sessions",
  export_files: "Exports",
};

export function entityLabel(table: string): string {
  return AUDIT_ENTITIES[table] ?? table;
}
