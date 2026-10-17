"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import type { components } from "@/types/api";
import { queryKeys } from "@/lib/api/queries/keys";
import { resolveBack, type BackSubject, type BackTarget } from "@/lib/back-target";
import { cn } from "@/lib/utils";

const TONES = {
  neutre: "text-foreground hover:underline",
  stock: "text-ventes hover:text-ventes-encre",
} as const;

/**
 * Le lien « ← … » au-dessus du titre, le même partout (fiches, sous-pages de L'argent,
 * écrans d'action). Avec `fallback` seul, il suit le `?from=` de l'adresse s'il reste sur
 * CoGes, et revient à `fallback` sinon (ADR 0082) ; avec `href`, il va toujours là.
 */
export function BackLink({
  fallback,
  fixed = false,
  tone = "neutre",
}: {
  fallback: BackTarget;
  /** Ignore `?from=` : l'écran n'a qu'un parent (modifier un article → sa fiche). */
  fixed?: boolean;
  /** `stock` : la couleur des liens de retour de la rubrique Stock (fiche article). */
  tone?: keyof typeof TONES;
}) {
  const className = TONES[tone];
  if (fixed) return <BackAnchor target={fallback} className={className} />;
  return (
    <Suspense fallback={<BackAnchor target={fallback} className={className} />}>
      <FromBackLink fallback={fallback} className={className} />
    </Suspense>
  );
}

function FromBackLink({ fallback, className }: { fallback: BackTarget; className: string }) {
  // `null` hors du routeur de l'application (tests de composant) : aucun `from`.
  const params = useSearchParams() as URLSearchParams | null;
  const from = params?.get("from") ?? null;
  const queryClient = useQueryClient();
  const nameOf = ({ kind, id }: BackSubject): string | undefined => {
    switch (kind) {
      case "customer":
      case "supplier":
        return queryClient.getQueryData<{ name: string }>(queryKeys.people.sheet(kind, id))?.name;
      case "product":
        return queryClient.getQueryData<components["schemas"]["ProductRead"]>(
          queryKeys.products.detail(id),
        )?.name;
      case "sale":
        return queryClient.getQueryData<components["schemas"]["SaleRead"]>(
          queryKeys.sales.detail(id),
        )?.sale_no;
    }
  };
  return <BackAnchor target={resolveBack(from, fallback, nameOf)} className={className} />;
}

function BackAnchor({ target, className }: { target: BackTarget; className: string }) {
  return (
    <Link
      href={target.href}
      className={cn(
        "inline-flex min-h-11 items-center gap-2 self-start font-bold pointer-coarse:min-h-12",
        className,
      )}
    >
      <ArrowLeft className="size-[22px]" aria-hidden />
      {target.label}
    </Link>
  );
}

/** Garde `from` quand un écran réécrit sa propre adresse (choix d'une personne, d'un jour). */
export function keepFrom(
  params: Record<string, string>,
  from: string | null,
): Record<string, string> {
  return from ? { ...params, from } : params;
}
