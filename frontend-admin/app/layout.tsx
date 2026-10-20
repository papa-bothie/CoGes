import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "CoGes — Administration",
  description: "Administration de la plateforme CoGes, réservée à l'équipe.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fr">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
