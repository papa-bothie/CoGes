"use client";

import { CloudOff } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { isApiError } from "@/lib/api/errors";
import { incidentReference } from "@/lib/incident";
import { labels } from "@/lib/labels";

const t = labels.incident;

/**
 * Écran d'erreur imprévue (ADR 0085), dans le ton de la maquette v2 : jamais de trace ni
 * de message brut, une phrase qui rassure, deux gestes, et la référence d'incident que le
 * commerçant peut nous lire au téléphone. Le titre reçoit le focus : un lecteur d'écran
 * annonce tout de suite ce qui s'est passé.
 */
export function IncidentScreen({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => title.current?.focus(), []);
  // La référence ne vient que de l'identifiant de requête de l'API ; un digest de Next
  // s'affiche tel quel, jamais transformé en fausse référence (« 0000 0000 », ADR 0088).
  const reference = isApiError(error) ? incidentReference(error.requestId) : null;
  const digest = isApiError(error) ? null : (error as { digest?: string } | null)?.digest;

  return (
    <main className="grid min-h-dvh place-items-center bg-background p-6">
      <div className="flex max-w-md flex-col items-center gap-4 text-center">
        <span className="grid size-16 place-items-center rounded-full bg-muted text-muted-foreground">
          <CloudOff className="size-8" aria-hidden />
        </span>
        <h1
          ref={title}
          tabIndex={-1}
          className="text-titre-page leading-[1.45] tracking-[-0.01em] outline-none"
        >
          {t.title}
        </h1>
        <p className="text-lg text-muted-foreground">{t.reassure}</p>
        {(reference || digest) && (
          <p className="rounded-carte border border-border bg-card px-4 py-2">
            <span className="block text-sm text-muted-foreground">{t.reference}</span>
            <span
              className={
                reference
                  ? "font-mono text-lg font-bold tracking-widest"
                  : "font-mono text-sm break-all"
              }
            >
              {reference ?? digest}
            </span>
          </p>
        )}
        <div className="flex flex-wrap justify-center gap-3">
          <Button onClick={onRetry}>{t.retry}</Button>
          <Button variant="outline" asChild>
            <Link href="/dashboard">{t.home}</Link>
          </Button>
        </div>
      </div>
    </main>
  );
}
