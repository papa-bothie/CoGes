"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Minus, Plus } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { cleanAmount } from "@/components/kit/amount-field";
import { articleTone } from "@/components/kit/list-row";
import { fieldClasses } from "@/components/kit/rubrique";
import { Ean13Barcode } from "@/components/products/ean13-barcode";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { Can, usePermission } from "@/hooks/use-permission";
import { withFrom } from "@/lib/back-target";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { useCategories } from "@/lib/api/queries/categories";
import { queryKeys } from "@/lib/api/queries/keys";
import { useStockFor } from "@/lib/api/queries/stock";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal, subtractDecimal } from "@/lib/decimal";
import { formatAmount, formatDateLong, formatQty } from "@/lib/format";
import { labels } from "@/lib/labels";
import { wholeUnits } from "@/lib/payment-amount";
import { historyKind, historyPhrase, historyQty, historyWhen } from "@/lib/stock-history";
import { qtyWithUnit } from "@/lib/units";
import { cn } from "@/lib/utils";

type Product = Schemas["ProductRead"];

const t = labels.stockScreens.sheet;
const MAX_LABELS = 500;
/** Lignes de « Ce qui s'est passé » (maquette 08) ; le journal complet reste sur l'écran
 * des mouvements. */
const HISTORY_SHOWN = 6;

const KIND_TONE = {
  out: "bg-stock-teinte text-stock-encre",
  loss: "bg-depenses-teinte text-depenses-encre",
  in: "bg-ventes-teinte text-ventes-encre",
  fix: "bg-argent-teinte text-argent-encre",
} as const;
const KIND_INK = {
  out: "text-stock-encre",
  loss: "text-depenses-encre",
  in: "text-ventes-encre",
  fix: "text-argent-encre",
} as const;
const KIND_SIGN = { out: "−", loss: "−", in: "+", fix: "=" } as const;

const SQUARE_TONES = [
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

const SECONDARY = cn(
  "inline-flex min-h-bouton items-center justify-center rounded-bouton border-2 border-input bg-card px-5 text-[17px] font-bold text-foreground",
  "outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50",
);
const PRIMARY = cn(
  "inline-flex min-h-bouton items-center justify-center rounded-bouton bg-stock px-5 text-[17px] font-bold text-primary-foreground",
  "outline-none hover:bg-stock/90 focus-visible:ring-3 focus-visible:ring-ring/50",
);

function unitWord(unit: string): string {
  return unit in labels.units ? labels.units[unit as keyof typeof labels.units] : unit;
}

/**
 * Fiche d'un article, maquette v2 (écran 08) : prix modifiables sur place (historisés,
 * ADR 0011), correction du stock, « Commander » qui ouvre une livraison préremplie
 * (ADR 0071), quatre tuiles, l'historique en phrases et l'étiquette à imprimer.
 */
export function ProductDetailView({ productId }: { productId: string }) {
  const { timeZone, currency } = useCompanyLocale();
  const [editing, setEditing] = useState(false);
  const [labelsCount, setLabelsCount] = useState("10");
  const [more, setMore] = useState(false);
  const canSeeHistory = usePermission("inventory:read");

  const product = useQuery({
    queryKey: queryKeys.products.detail(productId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/products/{product_id}", {
          params: { path: { product_id: productId } },
        }),
      ),
  });
  const stock = useStockFor([productId]);
  const history = useQuery({
    queryKey: [...queryKeys.products.detail(productId), "history"],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/analytics/products/{product_id}/history", {
          params: { path: { product_id: productId } },
        }),
      ),
    enabled: canSeeHistory,
  });
  const categories = useCategories();

  if (product.isError) {
    return <ErrorState error={product.error} onRetry={() => void product.refetch()} />;
  }
  if (!product.data) return <Skeleton className="mx-auto h-96 max-w-page" />;

  const data = product.data;
  const line = stock.data?.get(productId);
  const unit = unitWord(data.unit);
  const shelf = categories.data?.find((category) => category.id === data.category_id)?.name;
  const qty = line?.qty_on_hand ?? "0";
  const low = line ? line.status !== "ok" : false;
  const cost =
    line && compareDecimal(line.avg_cost, "0") === 1 ? line.avg_cost : (data.cost_price ?? null);
  const gain = cost ? subtractDecimal(data.unit_price ?? "0", cost) : null;
  const gainNegative = gain !== null && gain.startsWith("-");
  const monthSold = history.data?.month_sold_qty ?? "0";
  const perDay =
    history.data && history.data.month_days > 0
      ? (Number(monthSold) / history.data.month_days).toFixed(0)
      : "0";
  const copies = Math.min(MAX_LABELS, Math.max(0, Number(labelsCount) || 0));

  return (
    <div className="mx-auto flex max-w-page flex-col gap-5">
      <Link
        href="/products"
        className="inline-flex min-h-11 items-center gap-2 self-start font-bold text-ventes hover:text-ventes-encre pointer-coarse:min-h-12"
      >
        <ArrowLeft className="size-[22px]" aria-hidden />
        {t.back}
      </Link>

      <div className="flex flex-wrap items-center gap-4">
        <span
          aria-hidden
          className={cn(
            "flex size-[72px] shrink-0 items-center justify-center rounded-tuile text-3xl font-extrabold text-blanc",
            SQUARE_TONES[(articleTone(data.name) - 1) % SQUARE_TONES.length],
          )}
        >
          {data.name.trim().charAt(0).toLocaleUpperCase("fr-FR")}
        </span>
        <div className="flex-[1_1_240px]">
          <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{data.name}</h1>
          <p className="text-lg text-muted-foreground">{t.subtitle(shelf ?? null, unit)}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Can permission="prices:create">
            <button type="button" className={SECONDARY} onClick={() => setEditing((on) => !on)}>
              {t.changePrices}
            </button>
          </Can>
          <Can permission="inventory:update">
            <Link
              href={withFrom(`/inventory/adjust?product=${data.id}`, `/products/${data.id}`)}
              className={SECONDARY}
            >
              {t.adjust}
            </Link>
          </Can>
          <Can permission="inventory:create">
            <Link
              href={withFrom(`/inventory/receive?product=${data.id}`, `/products/${data.id}`)}
              className={PRIMARY}
            >
              {t.order}
            </Link>
          </Can>
        </div>
      </div>

      {editing && <PriceEditor product={data} onDone={() => setEditing(false)} />}

      <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-3">
        <Tile
          tone="bg-stock-teinte"
          ink={low ? "text-stock-encre" : "text-foreground"}
          label={t.inStock}
          value={data.is_stock_tracked ? qtyWithUnit(qty, data.unit) : "—"}
          detail={
            !data.is_stock_tracked
              ? t.notTracked
              : data.reorder_point
                ? t.alertAt(qtyWithUnit(data.reorder_point, data.unit))
                : t.noAlert
          }
          detailInk={low ? "text-stock-encre font-semibold" : "text-muted-foreground"}
        />
        <Tile
          tone="bg-ventes-teinte"
          ink="text-ventes-encre"
          label={t.price}
          value={formatAmount(data.unit_price, currency)}
          detail={cost ? t.bought(formatAmount(cost, currency)) : " "}
        />
        <Tile
          tone={gainNegative ? "bg-depenses-teinte" : "bg-ventes-teinte"}
          ink={gainNegative ? "text-depenses-encre" : "text-ventes-encre"}
          label={t.gain(unit)}
          value={gain ? formatAmount(gain, currency).replace("-", "−") : "—"}
          detail={t.gainHint}
        />
        <Tile
          tone="bg-argent-teinte"
          ink="text-argent-encre"
          label={t.soldMonth}
          value={qtyWithUnit(monthSold, data.unit)}
          detail={t.perDay(qtyWithUnit(perDay, data.unit))}
        />
      </div>

      <div className="flex flex-wrap items-start gap-5">
        {canSeeHistory && (
          <section className="min-w-0 flex-[3_1_460px] rounded-carte border border-border bg-card p-carte">
            <h2 className="text-titre-carte">{t.history.title}</h2>
            <div className="mt-2">
              {history.isPending ? (
                <Skeleton className="h-48 w-full" />
              ) : (history.data?.items.length ?? 0) === 0 ? (
                <p className="border-t border-filet pt-3 text-muted-foreground">
                  {t.history.empty}
                </p>
              ) : (
                history.data?.items.slice(0, HISTORY_SHOWN).map((item) => {
                  const kind = historyKind(item);
                  return (
                    <div
                      key={item.movement_id}
                      className="flex items-center gap-3 border-t border-filet py-3"
                    >
                      <span
                        aria-hidden
                        className={cn(
                          "flex size-10 shrink-0 items-center justify-center rounded-mini text-lg font-extrabold",
                          KIND_TONE[kind],
                        )}
                      >
                        {KIND_SIGN[kind]}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block font-bold">{historyPhrase(item)}</span>
                        <span className="block text-muted-foreground">
                          {historyWhen(item.occurred_at, timeZone)}
                        </span>
                      </span>
                      <span className={cn("text-lg font-extrabold numeric", KIND_INK[kind])}>
                        {historyQty(item, data.unit)}
                      </span>
                    </div>
                  );
                })
              )}
            </div>
          </section>
        )}

        <section className="flex min-w-0 flex-[2_1_320px] flex-col gap-3.5 rounded-carte border border-border bg-card p-carte">
          <h2 className="text-titre-carte">{t.label}</h2>
          <div className="flex flex-col items-center gap-1.5 rounded-touche border-2 border-dashed border-input bg-recu-papier p-4 text-recu-encre">
            <p className="font-bold">{data.name}</p>
            <p className="text-[30px] leading-tight font-extrabold numeric">
              {formatAmount(data.unit_price, currency)}
            </p>
            {data.barcode && <Ean13Barcode code={data.barcode} className="h-[76px] w-auto" />}
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="flex-[1_1_140px] font-bold">{t.howManyLabels}</span>
            <button
              type="button"
              className="flex size-[52px] items-center justify-center rounded-touche border-2 border-input bg-card outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50"
              onClick={() => setLabelsCount(String(Math.max(1, copies - 1)))}
              aria-label={t.oneLess}
            >
              <Minus className="size-5" aria-hidden />
            </button>
            <input
              inputMode="numeric"
              autoComplete="off"
              aria-label={t.labelsCount}
              value={labelsCount}
              onChange={(event) => setLabelsCount(cleanAmount(event.target.value).slice(0, 3))}
              className={cn(
                fieldClasses("stock"),
                "min-h-[52px] w-20 text-center text-[22px] font-bold numeric",
              )}
            />
            <button
              type="button"
              className="flex size-[52px] items-center justify-center rounded-touche border-2 border-input bg-card outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50"
              onClick={() => setLabelsCount(String(Math.min(MAX_LABELS, copies + 1)))}
              aria-label={t.oneMore}
            >
              <Plus className="size-5" aria-hidden />
            </button>
          </div>
          <Link
            href={`/products/${data.id}/etiquette?count=${copies}`}
            aria-disabled={copies === 0}
            className={cn(PRIMARY, copies === 0 && "pointer-events-none opacity-50")}
          >
            {t.print(copies)}
          </Link>
          <button
            type="button"
            onClick={() => setMore((open) => !open)}
            aria-expanded={more}
            className="min-h-12 text-left font-bold text-encre-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {more ? t.less : t.more}
          </button>
          {more && (
            <dl className="flex flex-col gap-1.5 rounded-touche bg-muted px-3.5 py-3">
              <Info label={t.sku} value={data.sku} />
              <Info label={t.barcode} value={data.barcode ?? "—"} />
              <Info
                label={t.tax}
                value={
                  compareDecimal(data.default_tax_rate ?? "0", "0") === 1
                    ? `${formatQty(String(Number(data.default_tax_rate) * 100))} %`
                    : t.noTax
                }
              />
              <Info label={t.createdAt} value={formatDateLong(data.created_at, timeZone)} />
            </dl>
          )}
        </section>
      </div>
    </div>
  );
}

function Tile({
  tone,
  ink,
  label,
  value,
  detail,
  detailInk = "text-muted-foreground",
}: {
  tone: string;
  ink: string;
  label: string;
  value: ReactNode;
  detail: ReactNode;
  detailInk?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1 rounded-tuile p-[18px]", tone)}>
      <span className="font-semibold">{label}</span>
      <span className={cn("text-[32px] leading-tight font-extrabold numeric", ink)}>{value}</span>
      <span className={detailInk}>{detail}</span>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-bold numeric">{value}</dd>
    </div>
  );
}

/** « Changer les prix » : vente et achat tapés librement, un nouvel intervalle de prix. */
function PriceEditor({ product, onDone }: { product: Product; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [price, setPrice] = useState(wholeUnits(product.unit_price).toString());
  const [cost, setCost] = useState(
    product.cost_price ? wholeUnits(product.cost_price).toString() : "",
  );
  const [error, setError] = useState<string | null>(null);

  const change = useMutation({
    meta: { toastError: false },
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/products/{product_id}/prices", {
          params: { path: { product_id: product.id } },
          body: { unit_price: price, cost_price: cost || null },
        }),
      ),
    onSuccess: () => {
      for (const key of [queryKeys.products.all, queryKeys.stock.all]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      toast.success(t.saved);
      onDone();
    },
    onError: (failure) => setError(errorMessage(failure)),
  });

  return (
    <section className="flex flex-wrap items-end gap-4 rounded-carte border-2 border-stock-anneau bg-card p-carte">
      <label className="flex-[1_1_200px]">
        <span className="mb-1.5 block font-bold">{t.salePrice}</span>
        <input
          inputMode="numeric"
          autoComplete="off"
          value={price}
          onChange={(event) => setPrice(cleanAmount(event.target.value))}
          className={cn(fieldClasses("stock"), "min-h-[58px] px-4 text-[22px] font-bold numeric")}
        />
      </label>
      <label className="flex-[1_1_200px]">
        <span className="mb-1.5 block font-bold">{t.buyPrice}</span>
        <input
          inputMode="numeric"
          autoComplete="off"
          value={cost}
          onChange={(event) => setCost(cleanAmount(event.target.value))}
          className={cn(fieldClasses("stock"), "min-h-[58px] px-4 text-[22px] font-bold numeric")}
        />
      </label>
      <button
        type="button"
        className={PRIMARY}
        disabled={!price || change.isPending}
        onClick={() => {
          setError(null);
          change.mutate();
        }}
      >
        {t.save}
      </button>
      <FieldError message={error} />
    </section>
  );
}
