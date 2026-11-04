"use client";

import { useState } from "react";

import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

/**
 * La description (ou la référence d'un homonyme) sous le nom d'un article, sur une ligne
 * tronquée (ADR 0108). Le texte complet reste dans le DOM pour le lecteur d'écran et en
 * infobulle au survol ; `expandable` (hors d'un bouton) le déplie au toucher. Rien sans texte.
 */
export function ProductHint({
  text,
  name,
  expandable = false,
  className,
}: {
  text: string | undefined;
  name: string;
  expandable?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  const classes = cn(
    "block max-w-full text-left text-sm font-medium text-muted-foreground",
    open ? "break-words whitespace-pre-line" : "truncate",
    className,
  );
  if (!expandable) {
    return (
      <span className={classes} title={text} data-slot="product-hint">
        {text}
      </span>
    );
  }
  return (
    <button
      type="button"
      title={text}
      aria-expanded={open}
      aria-label={open ? undefined : `${labels.products.description.showAll(name)} : ${text}`}
      onClick={() => setOpen((value) => !value)}
      data-slot="product-hint"
      className={cn(
        classes,
        "min-h-6 outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
      )}
    >
      {text}
    </button>
  );
}
