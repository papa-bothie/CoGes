"use client";

import type { ReactNode } from "react";

/** Titre `h1` + compteur à gauche, action principale à droite (motif du prototype). */
export function PageHeader({
  title,
  count,
  actions,
}: {
  title: string;
  count?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-page-title">{title}</h1>
        {count !== undefined && <p className="mt-1 text-sm text-muted-foreground">{count}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
