"use client";

import { Check, MessageCircle, Printer } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import type { Schemas } from "@/lib/api/schema";
import { formatAmount } from "@/lib/format";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { receiptText, whatsappLink } from "@/lib/whatsapp";

const t = labels.sales.editor.success;

const SECONDARY = cn(
  "inline-flex min-h-bouton flex-[1_1_200px] items-center justify-center gap-2.5 rounded-bouton border-2 border-input bg-card px-[22px] text-lg font-bold text-foreground",
  "outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50",
);

/**
 * Écran de succès d'une vente (maquette 02d) : rond vert coché, montant, ce qui a été payé
 * ou ce qui reste dû, puis « Nouvelle vente », le reçu et WhatsApp (lien `wa.me`, sans API
 * payante).
 */
export function SaleSuccess({
  sale,
  line,
  shop,
  phone,
  timeZone,
  currency,
  onNewSale,
}: {
  sale: Schemas["SaleDetail"];
  line: string;
  shop: string;
  phone: string | null;
  timeZone: string;
  currency: string;
  onNewSale: () => void;
}) {
  const text = receiptText(sale, { shop, timeZone, currency });
  return (
    <div className="flex justify-center pt-10">
      <section
        aria-live="polite"
        className="flex w-full max-w-[520px] flex-col items-center gap-3.5 rounded-carte border border-border bg-card px-7 py-10 text-center"
      >
        <span
          aria-hidden
          className="flex size-[88px] items-center justify-center rounded-full bg-ventes text-primary-foreground"
        >
          <Check className="size-12" strokeWidth={2.5} />
        </span>
        <h1 className="text-titre-page tracking-[-0.01em]">{t.title}</h1>
        <p className="text-[40px] leading-tight font-extrabold numeric">
          {formatAmount(sale.total, currency)}
        </p>
        <p className="text-lg text-muted-foreground">{line}</p>
        <div className="mt-3 flex w-full flex-wrap justify-center gap-3">
          <Button
            variant="ventes"
            size="standard"
            className="flex-[1_1_200px] text-lg"
            onClick={onNewSale}
          >
            {t.newSale}
          </Button>
        </div>
        <div className="flex w-full flex-wrap justify-center gap-3">
          <Link href={`/sales/${sale.id}/receipt`} className={SECONDARY}>
            <Printer className="size-[22px]" aria-hidden />
            {t.print}
          </Link>
          <a
            href={whatsappLink(text, phone)}
            target="_blank"
            rel="noopener noreferrer"
            className={SECONDARY}
          >
            <MessageCircle className="size-[22px]" aria-hidden />
            {labels.whatsapp.send}
          </a>
        </div>
        <Link
          href="/dashboard"
          className="mt-1.5 text-libelle text-ventes underline underline-offset-2 hover:text-ventes-encre"
        >
          {t.home}
        </Link>
      </section>
    </div>
  );
}
