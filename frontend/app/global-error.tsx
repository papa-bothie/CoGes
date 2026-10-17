"use client";

import "./globals.css";

import { IncidentScreen } from "@/components/incident-screen";

/**
 * Erreur dans la mise en page racine (ADR 0085) : ce fichier remplace tout le document,
 * il porte donc ses propres `<html>` et `<body>`. Thème du système (pas de bascule ici).
 */
export default function GlobalError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  return (
    <html lang="fr">
      <body>
        <title>Un souci de notre côté · CoGes</title>
        <IncidentScreen error={error} onRetry={retry} />
      </body>
    </html>
  );
}
