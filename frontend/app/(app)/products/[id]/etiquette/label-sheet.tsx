"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Printer } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ErrorState } from "@/components/error-state";
import { QuantityStepper } from "@/components/kit/quantity-stepper";
import { Ean13Barcode } from "@/components/products/ean13-barcode";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import { isValidEan13 } from "@/lib/barcode/ean13";
import { formatAmount } from "@/lib/format/money";
import { labels } from "@/lib/labels";

/** Au plus une planche raisonnable : au-delà, on imprime plusieurs fois. */
const MAX_LABELS = 200;

/**
 * Étiquettes d'un article (ADR 0066) : code-barres, nom et prix, autant que demandé. Une
 * page imprimable par le navigateur, sans service externe. Le nombre se tape librement.
 */
export function LabelSheet({ productId }: { productId: string }) {
  const { currency } = useCompanyLocale();
  const [count, setCount] = useState("1");
  const t = labels.products.labelPage;
  const product = useQuery({
    queryKey: queryKeys.products.detail(productId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/products/{product_id}", {
          params: { path: { product_id: productId } },
        }),
      ),
  });

  if (product.isError) {
    return <ErrorState error={product.error} onRetry={() => void product.refetch()} />;
  }
  if (!product.data) return <Skeleton className="h-64 w-full" />;
  const data = product.data;
  const code = data.barcode ?? "";
  const copies = Math.min(
    MAX_LABELS,
    Math.max(0, Math.floor(Number(count.replace(",", ".")) || 0)),
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4 print:hidden">
        <Link
          href={`/products/${data.id}`}
          className="inline-flex min-h-cible items-center gap-1 text-corps text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" aria-hidden />
          {t.back}
        </Link>
        <div className="flex flex-wrap items-end gap-4">
          <div className="space-y-2">
            <p className="text-libelle">{t.count}</p>
            <QuantityStepper
              value={count}
              onChange={setCount}
              itemName={t.title}
              min={1}
              rubrique="stock"
            />
          </div>
          <Button variant="stock" size="standard" onClick={() => window.print()}>
            <Printer aria-hidden />
            {t.print}
          </Button>
        </div>
      </div>
      {code && !isValidEan13(code) && (
        <p className="text-corps text-muted-foreground print:hidden">{t.notEan}</p>
      )}
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(60mm,1fr))] gap-3 print:gap-1">
        {Array.from({ length: copies }, (_, index) => (
          <li
            key={index}
            className="break-inside-avoid space-y-1 rounded-mini border border-dashed border-input bg-recu-papier p-3 text-recu-encre"
          >
            <p className="truncate text-petit font-bold">{data.name}</p>
            <p className="text-titre-carte font-extrabold numeric">
              {formatAmount(data.unit_price, currency)}
            </p>
            {isValidEan13(code) ? (
              <Ean13Barcode code={code} className="h-16 w-full" />
            ) : (
              <p className="font-receipt text-corps tracking-widest">{code}</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
