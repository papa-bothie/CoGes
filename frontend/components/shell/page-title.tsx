"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

type PageTitleState = { title: string | null; setTitle: (title: string | null) => void };

const PageTitleContext = createContext<PageTitleState>({ title: null, setTitle: () => undefined });

/**
 * Titre `h1` de la page courante, déclaré par `PageHeader` et lu par l'en-tête pour son fil
 * d'Ariane : l'en-tête ne devine jamais le titre d'une page (vente, fiche…).
 */
export function PageTitleProvider({ children }: { children: ReactNode }) {
  const [title, setTitle] = useState<string | null>(null);
  const value = useMemo(() => ({ title, setTitle }), [title]);
  return <PageTitleContext.Provider value={value}>{children}</PageTitleContext.Provider>;
}

export function usePageTitle(): string | null {
  return useContext(PageTitleContext).title;
}

export function useDeclarePageTitle(title: string) {
  const { setTitle } = useContext(PageTitleContext);
  useEffect(() => {
    setTitle(title);
    return () => setTitle(null);
  }, [title, setTitle]);
}
