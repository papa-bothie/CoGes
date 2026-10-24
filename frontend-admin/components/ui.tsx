import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

/**
 * Petit kit de l'administration (ADR 0094) : la couleur ne sert qu'aux statuts et à
 * l'action principale de la page ; tout le reste est en encre, trait et papier.
 */
export const BUTTON = {
  primary:
    "inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2 font-semibold text-accent-encre disabled:opacity-60",
  secondary:
    "inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-champ bg-surface px-4 py-2 font-semibold text-encre hover:bg-voile disabled:opacity-60",
  danger:
    "inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-danger px-4 py-2 font-semibold text-surface disabled:opacity-60",
  quiet:
    "inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-3 py-2 font-semibold text-encre hover:bg-voile disabled:opacity-60",
} as const;

export const FIELD =
  "w-full min-h-11 rounded-lg border border-champ bg-surface px-3 py-2 text-encre placeholder:text-encre-douce";
export const LABEL = "block font-semibold";

export function PageHeader({
  title,
  description,
  actions,
  id,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  id: string;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0 space-y-1">
        <h1 id={id} className="text-2xl font-bold tracking-tight">
          {title}
        </h1>
        {description && <div className="text-encre-douce">{description}</div>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Card({
  children,
  className = "",
  ...props
}: ComponentProps<"section"> & { children: ReactNode }) {
  return (
    <section {...props} className={`rounded-xl border border-trait bg-surface p-5 ${className}`}>
      {children}
    </section>
  );
}

const TONES = {
  succes: "bg-succes-teinte text-succes",
  danger: "bg-danger-teinte text-danger",
  attention: "bg-attention-teinte text-attention",
  info: "bg-info-teinte text-info",
} as const;

/** Message de résultat : `status` pour une réussite, `alert` pour une erreur. */
export function Notice({ tone, children }: { tone: keyof typeof TONES; children: ReactNode }) {
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={`rounded-lg px-4 py-3 ${TONES[tone]}`}
    >
      {children}
    </div>
  );
}

/** Puce de filtre : un lien qui garde l'état dans l'adresse, marqué quand il est actif. */
export function Chip({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: ReactNode;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "true" : undefined}
      className={`cible inline-flex min-h-9 items-center rounded-full border px-3 py-1 text-sm font-semibold ${
        active
          ? "border-accent bg-accent-teinte text-succes"
          : "border-champ bg-surface text-encre-douce hover:text-encre"
      }`}
    >
      {children}
    </Link>
  );
}

/** Pastille de statut : un mot, jamais la couleur seule. */
export function Pill({
  tone,
  children,
}: {
  tone: keyof typeof TONES | "neutre";
  children: ReactNode;
}) {
  const style = tone === "neutre" ? "bg-voile text-encre-douce" : TONES[tone];
  return (
    <span className={`inline-flex rounded-full px-2.5 py-0.5 text-sm font-semibold ${style}`}>
      {children}
    </span>
  );
}

export function Skeleton({ rows = 5, label }: { rows?: number; label: string }) {
  return (
    <div role="status" aria-label={label} className="space-y-2">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="h-12 animate-pulse rounded-lg bg-voile" />
      ))}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-champ bg-surface px-6 py-10 text-center">
      <p className="font-semibold">{title}</p>
      {children && <div className="mt-1 text-encre-douce">{children}</div>}
    </div>
  );
}

export function Pager({
  page,
  pages,
  href,
}: {
  page: number;
  pages: number;
  href: (page: number) => string;
}) {
  if (pages <= 1) return null;
  return (
    <nav aria-label="Pages" className="flex items-center justify-between gap-3">
      {page > 1 ? (
        <Link href={href(page - 1)} className={BUTTON.secondary}>
          Précédente
        </Link>
      ) : (
        <span />
      )}
      <span className="text-encre-douce">
        Page {page} sur {pages}
      </span>
      {page < pages ? (
        <Link href={href(page + 1)} className={BUTTON.secondary}>
          Suivante
        </Link>
      ) : (
        <span />
      )}
    </nav>
  );
}
