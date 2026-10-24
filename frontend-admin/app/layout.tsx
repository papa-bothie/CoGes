import type { Metadata } from "next";
import localFont from "next/font/local";

import "./globals.css";

// Police de la maquette v2 (ADR 0064), copiée de l'app commerçante (licence OFL,
// app/fonts/OFL-Figtree.txt) : les deux applications se déploient séparément.
const figtree = localFont({
  src: "./fonts/figtree-latin.woff2",
  weight: "300 900",
  variable: "--font-figtree",
  display: "swap",
  fallback: ["system-ui", "sans-serif"],
});

export const metadata: Metadata = {
  // Chaque onglet dit qu'on est dans l'administration (ADR 0094).
  title: { default: "Administration · CoGes", template: "Administration · %s" },
  description: "Administration de la plateforme CoGes, réservée à l'équipe.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fr" className={figtree.variable}>
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
