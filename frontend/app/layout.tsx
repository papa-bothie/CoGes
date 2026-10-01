import type { Metadata } from "next";
import { Inter } from "next/font/google";

import { DENSITY_BOOT_SCRIPT } from "@/lib/density-boot";

import "./globals.css";
import { Providers } from "./providers";

// Chiffres tabulaires disponibles (`tnum`) : indispensables pour aligner les montants.
// Axe optique : les titres et grands chiffres prennent le dessin « display », plus serré.
const inter = Inter({
  subsets: ["latin"],
  axes: ["opsz"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "CoGes", template: "%s · CoGes" },
  description: "Gestion commerciale pour PME : ventes, stock, argent, décisions.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="fr" className={inter.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: DENSITY_BOOT_SCRIPT }} />
      </head>
      <body className="min-h-dvh">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
