/**
 * Clés TanStack Query, par ressource. Une écriture invalide la **racine** de la
 * ressource touchée et celles qu'elle déplace (stock, argent, tableau de bord) : aucune
 * mise à jour optimiste sur ce qui touche au stock ou à l'argent.
 */
export const queryKeys = {
  dashboard: ["dashboard"] as const,
  systemOutbox: ["system", "outbox"] as const,
  sales: {
    all: ["sales"] as const,
    list: (params: Record<string, unknown>) => ["sales", "list", params] as const,
    detail: (id: string) => ["sales", "detail", id] as const,
    receipt: (id: string) => ["sales", "receipt", id] as const,
    returns: (id: string) => ["sales", "returns", id] as const,
  },
  saleReturns: {
    all: ["sale-returns"] as const,
    detail: (id: string) => ["sale-returns", "detail", id] as const,
  },
  stock: {
    all: ["stock"] as const,
    forProducts: (ids: readonly string[]) => ["stock", "products", [...ids].sort()] as const,
    list: (params: Record<string, unknown>) => ["stock", "list", params] as const,
  },
  movements: {
    all: ["movements"] as const,
    list: (params: Record<string, unknown>) => ["movements", "list", params] as const,
  },
  products: {
    all: ["products"] as const,
    search: ["products", "search"] as const,
    list: (params: Record<string, unknown>) => ["products", "list", params] as const,
    detail: (id: string) => ["products", "detail", id] as const,
    prices: (id: string) => ["products", "prices", id] as const,
  },
  categories: { all: ["categories"] as const },
  customers: {
    all: ["customers"] as const,
    search: ["customers", "search"] as const,
    // Sous `customers` : une fiche créée ou modifiée invalide aussi la liste de vente.
    choices: (term: string) => ["customers", "choices", term] as const,
    list: (params: Record<string, unknown>) => ["customers", "list", params] as const,
    detail: (id: string) => ["customers", "detail", id] as const,
  },
  /** Écrans 13 à 16 (ADR 0072) : listes et fiches composées par Analytics. */
  people: {
    all: ["people"] as const,
    list: (kind: string, params: Record<string, unknown>) =>
      ["people", kind, "list", params] as const,
    sheet: (kind: string, id: string) => ["people", kind, "sheet", id] as const,
    history: (kind: string, id: string, view: string) =>
      ["people", kind, "history", id, view] as const,
  },
  suppliers: {
    all: ["suppliers"] as const,
    list: (params: Record<string, unknown>) => ["suppliers", "list", params] as const,
    detail: (id: string) => ["suppliers", "detail", id] as const,
  },
  debts: {
    all: ["debts"] as const,
    list: (params: Record<string, unknown>) => ["debts", "list", params] as const,
  },
  payments: {
    all: ["payments"] as const,
    list: (params: Record<string, unknown>) => ["payments", "list", params] as const,
  },
  expenses: {
    all: ["expenses"] as const,
    list: (params: Record<string, unknown>) => ["expenses", "list", params] as const,
  },
  expenseCategories: { all: ["expense-categories"] as const },
  /** Tout ce que calcule Restitution : invalidé après chaque écriture d'argent. */
  analytics: {
    all: ["analytics"] as const,
    overview: (params: Record<string, unknown>) => ["analytics", "overview", params] as const,
    products: (params: Record<string, unknown>) => ["analytics", "products", params] as const,
    series: (params: Record<string, unknown>) => ["analytics", "series", params] as const,
    /** Écrans 17, 20 et 21 (ADR 0073). */
    money: (params: Record<string, unknown>) => ["analytics", "money", params] as const,
    cash: (day: string | null) => ["analytics", "cash", day] as const,
    expenses: ["analytics", "expenses-summary"] as const,
  },
  intelligence: {
    all: ["intelligence"] as const,
    summary: ["intelligence", "summary"] as const,
    insights: (params: Record<string, unknown>) => ["intelligence", "insights", params] as const,
    forecasts: (params: Record<string, unknown>) => ["intelligence", "forecasts", params] as const,
  },
  company: ["company"] as const,
  users: { all: ["users"] as const },
  roles: { all: ["roles"] as const, detail: (id: string) => ["roles", "detail", id] as const },
  permissions: ["permissions"] as const,
  audit: {
    all: ["audit"] as const,
    list: (params: Record<string, unknown>) => ["audit", "list", params] as const,
  },
  notifications: {
    all: ["notifications"] as const,
    list: (params: Record<string, unknown>) => ["notifications", "list", params] as const,
    unread: ["notifications", "unread"] as const,
  },
} as const;

/** Racines à invalider après une écriture d'argent (paiement, dette, dépense). */
export const MONEY_KEYS = [
  queryKeys.payments.all,
  queryKeys.debts.all,
  queryKeys.expenses.all,
  queryKeys.analytics.all,
  queryKeys.sales.all,
  queryKeys.dashboard,
  // Ce que doit chaque personne (écrans 13 à 16) suit ses dettes.
  queryKeys.people.all,
] as const;
