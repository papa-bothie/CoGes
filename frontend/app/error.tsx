"use client";

import { IncidentScreen } from "@/components/incident-screen";

/** Erreur imprévue dans une page (ADR 0085) : l'écran d'incident, jamais une page blanche. */
export default function Error({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  return <IncidentScreen error={error} onRetry={retry} />;
}
