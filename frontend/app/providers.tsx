"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { usePathname } from "next/navigation";
import { ThemeProvider } from "next-themes";
import { useState, type ReactNode } from "react";

import { PwaProvider } from "@/components/pwa/pwa-provider";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { makeQueryClient } from "@/lib/api/query";
import { isAlwaysLight } from "@/lib/theme/always-light";

/**
 * Thème : celui de la personne (clair, sombre, automatique), sauf sur les pages d'entrée,
 * toujours claires (prompt 39, ADR 0123). `forcedTheme` passe par le script de next-themes,
 * appliqué avant le premier affichage, et n'écrit rien dans le stockage. Recolorer un
 * conteneur (`.papier`) ne suffirait pas : `@custom-variant dark (&:is(.dark *))` laisserait
 * les classes `dark:` actives sous `html.dark`.
 */
export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(makeQueryClient);
  const pathname = usePathname();
  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
      forcedTheme={isAlwaysLight(pathname) ? "light" : undefined}
    >
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          {children}
          <PwaProvider />
          <Toaster richColors closeButton position="top-right" />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
