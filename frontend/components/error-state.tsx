import { AlertTriangle } from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/api/errors";
import { labels } from "@/lib/labels";

/** Échec d'une lecture : le message de l'API (déjà en français) et un bouton pour réessayer. */
export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <EmptyState
      icon={AlertTriangle}
      title={labels.errors.loadFailed}
      description={errorMessage(error)}
      className={className}
      action={
        onRetry && (
          <Button variant="outline" onClick={onRetry}>
            {labels.errors.retry}
          </Button>
        )
      }
    />
  );
}
