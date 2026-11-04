"use client";

import type { ReactNode } from "react";

import { useCompanyLogo } from "@/hooks/use-company-logo";
import type { Schemas } from "@/lib/api/schema";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

type Company = Schemas["ReceiptCompany"];
const t = labels.receipt;

/**
 * Pièces communes du ticket, de la facture et du bon de retour (prompt 35, bloc F, ADR 0112).
 *
 * Palette d'impression : uniquement les jetons `recu-*` (encre, gris, filet, en-tête,
 * papier), lisibles en noir et blanc ; aucune couleur de rubrique sur une pièce imprimée.
 */

/** Ligne gauche / droite d'un ticket ; le montant reste à droite, en chiffres tabulaires. */
export function ReceiptRow({
  left,
  right,
  className,
}: {
  left: ReactNode;
  right: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex justify-between gap-2", className)}>
      <span className="min-w-0">{left}</span>
      <span className="shrink-0 text-right numeric">{right}</span>
    </div>
  );
}

/** Le logo de la boutique, s'il y en a un ; `monochrome` pour le petit ticket thermique. */
export function ShopLogo({
  company,
  className,
  monochrome = false,
}: {
  company: Company;
  className?: string;
  monochrome?: boolean;
}) {
  const url = useCompanyLogo(company.logo_updated_at);
  if (!url) return null;
  return (
    // eslint-disable-next-line @next/next/no-img-element -- adresse data: locale (ADR 0111)
    <img
      src={url}
      alt={t.logoAlt(company.name)}
      className={cn("object-contain", monochrome && "grayscale", className)}
    />
  );
}

/** En-tête centré du petit ticket et du bon de retour : logo, nom, adresse, téléphone. */
export function TicketHeader({ company }: { company: Company }) {
  return (
    <div className="flex flex-col items-center text-center">
      <ShopLogo company={company} monochrome className="mb-1.5 max-h-14 max-w-[160px]" />
      <div className="text-base font-bold uppercase">{company.name}</div>
      {company.address && <div className="font-bold">{company.address}</div>}
      {company.phone && <div>{t.phone(company.phone)}</div>}
    </div>
  );
}
