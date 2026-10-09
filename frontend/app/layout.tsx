import type { Metadata } from "next";
import localFont from "next/font/local";

import "./globals.css";
import { Providers } from "./providers";

// Police de la maquette v2 (ADR 0064), variable (graisses 400 à 800 utilisées) ; chiffres
// tabulaires (`tnum`) pour aligner les montants. Fichiers de Google Fonts hébergés ici
// (licence OFL, app/fonts/OFL-*.txt) : celui que télécharge `next/font/google` n'a pas de table
// `prep`, et Chrome sous Linux élargit alors certaines lettres (« connect er »).
const figtree = localFont({
  // Sous-ensemble latin (U+0000-00FF, œ, €…) : tout le français.
  src: "./fonts/figtree-latin.woff2",
  weight: "300 900",
  variable: "--font-figtree",
  display: "swap",
  fallback: ["system-ui", "sans-serif"],
});

// Le reçu imprimé (ticket 80 mm et facture A4) prend JetBrains Mono, même hébergement.
const jetbrainsMono = localFont({
  src: "./fonts/jetbrains-mono-latin.woff2",
  weight: "400 700",
  variable: "--font-jetbrains-mono",
  display: "swap",
  fallback: ["ui-monospace", "monospace"],
});

export const metadata: Metadata = {
  title: { default: "CoGes", template: "%s · CoGes" },
  description: "Gestion commerciale pour PME : ventes, stock, argent, décisions.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="fr"
      className={`${figtree.variable} ${jetbrainsMono.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-dvh">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
