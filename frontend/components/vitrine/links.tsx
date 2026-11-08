import { MessageCircle } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { whatsappLink } from "@/content/vitrine";
import { cn } from "@/lib/utils";

/** Bouton plein ou bordé de la maquette v2, 48 px au moins (cible tactile). */
const BASE =
  "inline-flex min-h-cible items-center justify-center gap-2 rounded-bouton px-5 font-bold transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/60 [&_svg]:size-5 [&_svg]:shrink-0";
export const VARIANTS = {
  plein: "bg-primary text-primary-foreground hover:bg-primary/90",
  borde: "border-2 border-input bg-card text-foreground hover:bg-voile",
};

/** Lien `wa.me` : un simple lien, aucune requête de la page (prompt 37). */
export function WhatsAppLink({
  children,
  variant = "plein",
  className,
}: {
  children: ReactNode;
  variant?: keyof typeof VARIANTS;
  className?: string;
}) {
  return (
    <a
      href={whatsappLink()}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(BASE, VARIANTS[variant], className)}
    >
      <MessageCircle aria-hidden />
      {children}
      <span className="sr-only"> (ouvre WhatsApp)</span>
    </a>
  );
}

export function ButtonLink({
  href,
  children,
  variant = "plein",
  className,
}: {
  href: string;
  children: ReactNode;
  variant?: keyof typeof VARIANTS;
  className?: string;
}) {
  return (
    <Link href={href} className={cn(BASE, VARIANTS[variant], className)}>
      {children}
    </Link>
  );
}
