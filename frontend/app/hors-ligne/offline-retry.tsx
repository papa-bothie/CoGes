"use client";

import { Button } from "@/components/ui/button";
import { labels } from "@/lib/labels";

/** « Réessayer » : recharge l'adresse demandée, que le service worker n'a pas pu servir. */
export function OfflineRetry() {
  return <Button onClick={() => window.location.reload()}>{labels.pwa.offlineRetry}</Button>;
}
