import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { RUBRIQUE_CLASSES, RUBRIQUES, type Rubrique } from "./rubrique";

/** Initiales d'un nom : « Awa Diop » → « AD », « Riz brisé » → « RB », « Moussa » → « M ». */
export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  return words
    .slice(0, 2)
    .map((word) => word.charAt(0).toLocaleUpperCase("fr-FR"))
    .join("");
}

function hash(text: string): number {
  let value = 0;
  for (const char of text) value = (value * 31 + char.charCodeAt(0)) >>> 0;
  return value;
}

/** Teinte stable d'une personne, tirée de son nom (même nom, même couleur partout). */
export function personTone(name: string): Rubrique {
  return RUBRIQUES[hash(name) % RUBRIQUES.length] ?? "ventes";
}

/**
 * Avatar rond à initiales (44 px) : teinte et encre d'une rubrique. Sans nom (client de
 * passage), un point sur fond neutre.
 */
export function Avatar({
  name,
  rubrique,
  size = "normal",
}: {
  name: string | null;
  rubrique?: Rubrique;
  size?: "normal" | "moyen" | "grand";
}) {
  const dimension =
    size === "grand"
      ? "size-[52px] text-lg font-extrabold"
      : size === "moyen"
        ? "size-[46px] font-bold"
        : "size-11 font-bold";
  if (!name) {
    return (
      <span
        aria-hidden
        className={cn(
          "flex shrink-0 items-center justify-center rounded-full bg-voile text-muted-foreground",
          dimension,
        )}
      >
        ·
      </span>
    );
  }
  const tone = RUBRIQUE_CLASSES[rubrique ?? personTone(name)];
  return (
    <span
      aria-hidden
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full",
        tone.tint,
        tone.ink,
        dimension,
      )}
    >
      {initials(name)}
    </span>
  );
}

const ARTICLE_TONES = [
  "bg-article-1",
  "bg-article-2",
  "bg-article-3",
  "bg-article-4",
  "bg-article-5",
  "bg-article-6",
  "bg-article-7",
  "bg-article-8",
  "bg-article-9",
  "bg-article-10",
  "bg-article-11",
  "bg-article-12",
] as const;

/** Couleur stable d'un article (1 à 12), tirée de son identifiant ou de son nom. */
export function articleTone(key: string): number {
  return (hash(key) % ARTICLE_TONES.length) + 1;
}

/** Carré d'article à initiale (maquette 02, 07) : couleur pleine, lettre blanche. */
export function ProductSquare({
  name,
  tone,
  size = "normal",
}: {
  name: string;
  /** 1 à 12 ; par défaut tiré du nom. */
  tone?: number;
  size?: "petit" | "normal" | "moyen" | "grand" | "tres-grand";
}) {
  const index = (tone ?? articleTone(name)) - 1;
  return (
    <span
      aria-hidden
      className={cn(
        "flex shrink-0 items-center justify-center font-extrabold text-blanc",
        ARTICLE_TONES[index % ARTICLE_TONES.length],
        size === "tres-grand"
          ? "size-16 rounded-touche text-[26px]"
          : size === "grand"
            ? "size-[52px] rounded-touche text-xl"
            : size === "moyen"
              ? "size-[50px] rounded-touche text-[19px]"
              : size === "petit"
                ? "size-11 rounded-mini"
                : "size-12 rounded-touche text-[19px]",
      )}
    >
      {name.trim().charAt(0).toLocaleUpperCase("fr-FR")}
    </span>
  );
}

/**
 * Ligne de liste de la maquette v2 : visuel à gauche (avatar, carré), titre et sous-titre,
 * puis ce qui s'aligne à droite (montant, pastille). Filet en haut ; lien si `href`.
 */
export function ListRow({
  leading,
  title,
  subtitle,
  trailing,
  href,
  className,
}: {
  leading?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  trailing?: ReactNode;
  href?: string;
  className?: string;
}) {
  const content = (
    <>
      {leading}
      <div className="min-w-0 flex-1">
        <div className="truncate font-bold">{title}</div>
        {subtitle && <div className="truncate text-sm text-muted-foreground">{subtitle}</div>}
      </div>
      {trailing && <div className="flex shrink-0 items-center gap-3.5">{trailing}</div>}
    </>
  );
  const base = cn(
    "flex min-h-[72px] items-center gap-3.5 border-t border-filet py-3.5 text-foreground",
    className,
  );
  return href ? (
    <Link
      href={href}
      className={cn(
        base,
        "outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50",
      )}
    >
      {content}
    </Link>
  ) : (
    <div className={base}>{content}</div>
  );
}
