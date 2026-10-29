"use client";

import { useEffect } from "react";

import { IncidentScreen } from "@/components/incident-screen";
import { reportRenderError } from "@/lib/pwa/register";

/** Erreur imprévue dans une page (ADR 0085) : l'écran d'incident, jamais une page blanche. */
export default function Error({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  // Un fichier de l'ancienne version manque : un seul rechargement propre, au moment sûr.
  useEffect(() => reportRenderError(error), [error]);
  return <IncidentScreen error={error} onRetry={retry} />;
}
