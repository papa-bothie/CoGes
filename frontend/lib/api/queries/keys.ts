/**
 * Clés TanStack Query, par ressource. Une écriture invalide la **racine** de la
 * ressource touchée et celles qu'elle déplace (stock, argent, tableau de bord) : aucune
 * mise à jour optimiste sur ce qui touche au stock ou à l'argent.
 */
export const queryKeys = {
  dashboard: ["dashboard"] as const,
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
    list: (params: Record<string, unknown>) => ["customers", "list", params] as const,
    detail: (id: string) => ["customers", "detail", id] as const,
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
} as const;
