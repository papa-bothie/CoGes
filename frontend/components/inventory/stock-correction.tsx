"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarX,
  Check,
  Gift,
  Hammer,
  House,
  Minus,
  Plus,
  Search,
  ShieldAlert,
  Sigma,
  Truck,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { BackLink } from "@/components/back-link";
import { FieldError } from "@/components/field-error";
import { ChoiceTiles } from "@/components/kit/choice-tile";
import { ProductSquare } from "@/components/kit/list-row";
import { cleanQuantity } from "@/components/kit/quantity-stepper";
import { fieldClasses } from "@/components/kit/rubrique";
import { Skeleton } from "@/components/ui/skeleton";
import { Can } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal, parseDecimalInput, subtractDecimal } from "@/lib/decimal";
import { labels } from "@/lib/labels";
import { qtyWithUnit } from "@/lib/units";
import { cn } from "@/lib/utils";

type StockLine = Schemas["StockLine"];
type Reason = Schemas["StockReason"];
type Direction = "more" | "less";

/** Raisons de la maquette 10, dans son ordre (ADR 0067) ; la première est choisie d'office. */
const REASONS: Record<Direction, readonly { value: Reason; icon: LucideIcon }[]> = {
  less: [
    { value: "damaged", icon: Hammer },
    { value: "expired", icon: CalendarX },
    { value: "lost_or_stolen", icon: ShieldAlert },
    { value: "home_use", icon: House },
    { value: "count_error", icon: Sigma },
  ],
  more: [
    { value: "count_error", icon: Sigma },
    { value: "found", icon: Search },
    { value: "supplier_gift", icon: Gift },
  ],
};

const t = labels.stock.correction;

const STEP = cn(
  "flex size-[60px] shrink-0 items-center justify-center rounded-[18px] border-2 border-input bg-card text-[28px] font-bold text-foreground",
  "outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50",
);

function stockText(line: StockLine): string {
  if (line.status === "out") return t.out;
  const qty = qtyWithUnit(line.qty_on_hand, line.unit);
  return line.status === "low" ? t.left(qty) : qty;
}

/**
 * « Corriger le stock », maquette v2 (écran 10) : à gauche les articles (les plus bas
 * d'abord, ordre du serveur), à droite ce que le logiciel compte, Plus ou Moins dans la
 * boutique, combien, pourquoi en tuiles, puis « Valider la correction ». Rien au clavier :
 * le premier article, « Moins », 1 et « Abîmé ou cassé » sont choisis d'office. Le type du
 * mouvement se déduit de la raison, le coût est le CMP (ADR 0067).
 */
export function StockCorrection({ productId }: { productId?: string }) {
  const queryClient = useQueryClient();
  const idempotency = useIdempotencyKey();
  const [pickedId, setPickedId] = useState<string | undefined>(productId);
  const [direction, setDirection] = useState<Direction>("less");
  const [qty, setQty] = useState("1");
  const [reason, setReason] = useState<Reason>("damaged");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const stock = useQuery({
    queryKey: queryKeys.stock.list({ correction: true }),
    queryFn: () =>
      unwrap(api.GET("/api/v1/inventory/stock", { params: { query: { page_size: 100 } } })),
  });
  // L'article venu de sa fiche peut être au-delà des 100 premiers : on le lit à part.
  const asked = useQuery({
    queryKey: queryKeys.stock.list({ correction: true, product_id: productId }),
    enabled: Boolean(productId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/inventory/stock", {
          params: { query: { product_id: productId ? [productId] : [] } },
        }),
      ),
  });
  const listed = stock.data?.items ?? [];
  const extra = (asked.data?.items ?? []).filter(
    (item) => !listed.some((other) => other.product_id === item.product_id),
  );
  const lines = [...extra, ...listed].filter((line) => line.is_stock_tracked !== false);
  // D'office, le premier article qui a encore du stock : « Moins 1 » doit pouvoir partir.
  const loading = stock.isPending || asked.isLoading;
  const line = loading
    ? undefined
    : (lines.find((item) => item.product_id === pickedId) ??
      lines.find((item) => item.status !== "out") ??
      lines[0]);

  const parsed = parseDecimalInput(qty);
  const positive = parsed !== null && compareDecimal(parsed, "0") === 1;
  const after =
    line && parsed !== null
      ? subtractDecimal(line.qty_on_hand, direction === "less" ? parsed : `-${parsed}`)
      : null;
  const tooMany = after !== null && compareDecimal(after, "0") === -1;
  const ready = Boolean(line) && positive && !tooMany;

  const save = useMutation({
    meta: { toastError: false },
    mutationFn: (body: Schemas["MovementCreate"]) =>
      unwrap(api.POST("/api/v1/inventory/movements", { body, headers: idempotency.headers })),
    onSuccess: () => {
      idempotency.renew();
      for (const key of [queryKeys.stock.all, queryKeys.products.all, queryKeys.movements.all]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      if (line && after !== null) {
        setDone(
          t.doneLine(
            line.name,
            qtyWithUnit(after, line.unit),
            labels.stock.reasons[reason].toLocaleLowerCase("fr-FR"),
          ),
        );
      }
      setQty("1");
    },
    onError: (failure) => setError(errorMessage(failure)),
  });

  const pickDirection = (next: Direction) => {
    setDirection(next);
    setReason(REASONS[next][0]!.value);
    setDone(null);
  };
  const step = (delta: 1 | -1) => {
    const current = Number((parseDecimalInput(qty) ?? "0").split(".")[0]);
    setQty(String(Math.max(1, current + delta)));
    setDone(null);
  };

  return (
    <div className="mx-auto flex max-w-page flex-col gap-5">
      <BackLink fallback={{ href: "/products", label: labels.kit.nav.stock }} tone="stock" />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{t.title}</h1>
        <div className="flex flex-wrap gap-2.5">
          <Can permission="products:create">
            <Link
              href="/products/new"
              className="inline-flex min-h-bouton items-center gap-2.5 rounded-bouton border-2 border-input bg-card px-5 text-[17px] font-bold text-foreground outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <Plus className="size-[22px]" aria-hidden />
              {labels.stock.newProduct}
            </Link>
          </Can>
          <Link
            href="/inventory/receive"
            className="inline-flex min-h-bouton items-center gap-2.5 rounded-bouton bg-stock px-5 text-[17px] font-bold text-primary-foreground outline-none hover:bg-stock/90 focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <Truck className="size-[22px]" aria-hidden />
            {labels.stock.receive}
          </Link>
        </div>
      </div>

      <div className="flex flex-wrap items-start gap-5">
        <section className="min-w-0 flex-[2_1_320px] rounded-carte border border-border bg-card p-3">
          <p id="which" className="px-2.5 pt-2 pb-1 text-libelle">
            {t.whichProduct}
          </p>
          {loading ? (
            <Skeleton className="h-72 w-full" />
          ) : (
            <div role="radiogroup" aria-labelledby="which">
              {lines.map((item) => {
                const picked = item.product_id === line?.product_id;
                return (
                  <button
                    key={item.product_id}
                    type="button"
                    role="radio"
                    aria-checked={picked}
                    onClick={() => {
                      setPickedId(item.product_id);
                      setQty("1");
                      setDone(null);
                    }}
                    className={cn(
                      "flex min-h-[72px] w-full items-center gap-3 rounded-[18px] border-2 px-3.5 py-2.5 text-left",
                      "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                      picked ? "border-stock bg-stock-teinte" : "border-transparent hover:bg-muted",
                    )}
                  >
                    <ProductSquare name={item.name} />
                    <span className="min-w-0 flex-1">
                      <span className="block text-libelle">{item.name}</span>
                      <span
                        className={cn(
                          "block font-semibold",
                          item.status === "ok" ? "text-muted-foreground" : "text-stock-encre",
                        )}
                      >
                        {stockText(item)}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </section>

        <section className="flex min-w-0 flex-[3_1_460px] flex-col gap-[22px] rounded-carte border border-border bg-card p-carte">
          {done && (
            <p
              role="status"
              className="flex items-center gap-3.5 rounded-[18px] bg-ventes-teinte px-[18px] py-4 text-lg font-bold text-ventes-encre"
            >
              <span
                aria-hidden
                className="flex size-11 shrink-0 items-center justify-center rounded-full bg-ventes text-primary-foreground"
              >
                <Check className="size-6" strokeWidth={2.6} />
              </span>
              {done}
            </p>
          )}
          {line ? (
            <>
              <div className="flex items-center gap-4">
                <ProductSquare name={line.name} size="tres-grand" />
                <div className="min-w-0 flex-1">
                  <p className="text-[22px] leading-tight font-extrabold">{line.name}</p>
                  <p className="text-[17px] text-muted-foreground">
                    {t.counts}{" "}
                    <span className="font-extrabold numeric text-foreground">
                      {qtyWithUnit(line.qty_on_hand, line.unit)}
                    </span>
                  </p>
                </div>
              </div>

              <div>
                <p id="in-shop" className="mb-2.5 text-libelle">
                  {t.inShop}
                </p>
                <div role="radiogroup" aria-labelledby="in-shop" className="flex flex-wrap gap-3">
                  {(["more", "less"] as const).map((value) => {
                    const Icon = value === "more" ? Plus : Minus;
                    const picked = direction === value;
                    return (
                      <button
                        key={value}
                        type="button"
                        role="radio"
                        aria-checked={picked}
                        onClick={() => pickDirection(value)}
                        className={cn(
                          "flex min-h-20 flex-[1_1_200px] items-center justify-center gap-3 rounded-tuile border-2 text-[19px] font-extrabold",
                          "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                          !picked && "border-input bg-card text-encre-2 hover:bg-voile",
                          picked &&
                            value === "more" &&
                            "border-ventes bg-ventes-teinte text-ventes-encre",
                          picked &&
                            value === "less" &&
                            "border-stock bg-stock-teinte text-stock-encre",
                        )}
                      >
                        <Icon className="size-7" aria-hidden />
                        {value === "more" ? t.more : t.less}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <p className="mb-2.5 text-libelle">{t.howMany}</p>
                <div className="flex flex-wrap items-center gap-3.5">
                  <button
                    type="button"
                    className={STEP}
                    onClick={() => step(-1)}
                    aria-label={labels.kit.decrease(line.name)}
                  >
                    <span aria-hidden>−</span>
                  </button>
                  <input
                    inputMode="decimal"
                    autoComplete="off"
                    aria-label={`${labels.kit.quantity} : ${line.name}`}
                    value={qty}
                    onChange={(event) => {
                      setQty(cleanQuantity(event.target.value));
                      setDone(null);
                    }}
                    className={cn(
                      fieldClasses("stock"),
                      "h-[60px] w-[110px] rounded-[18px] text-center text-[30px] font-extrabold numeric",
                    )}
                  />
                  <button
                    type="button"
                    className={STEP}
                    onClick={() => step(1)}
                    aria-label={labels.kit.increase(line.name)}
                  >
                    <span aria-hidden>+</span>
                  </button>
                  {after !== null && !tooMany && (
                    <p
                      role="status"
                      className="ml-auto rounded-champ bg-voile px-4 py-3 text-[17px] font-bold"
                    >
                      {t.after}{" "}
                      <span
                        className={cn(
                          "text-[22px] numeric",
                          line.reorder_point && compareDecimal(after, line.reorder_point) !== 1
                            ? "text-stock-encre"
                            : "text-ventes-encre",
                        )}
                      >
                        {qtyWithUnit(after, line.unit)}
                      </span>
                    </p>
                  )}
                </div>
                {tooMany && (
                  <FieldError message={t.tooMany(qtyWithUnit(line.qty_on_hand, line.unit))} />
                )}
              </div>

              <div>
                <p className="mb-2.5 text-libelle">{t.why}</p>
                <ChoiceTiles
                  label={t.why}
                  value={reason}
                  onValueChange={(next) => {
                    setReason(next);
                    setDone(null);
                  }}
                  rubrique="stock"
                  className="grid-cols-[repeat(auto-fill,minmax(150px,1fr))]"
                  choices={REASONS[direction].map((choice) => ({
                    value: choice.value,
                    label: labels.stock.reasons[choice.value],
                    icon: choice.icon,
                  }))}
                />
              </div>

              <FieldError message={error} />
              <button
                type="button"
                disabled={!ready || save.isPending}
                onClick={() => {
                  if (!line || parsed === null) return;
                  setError(null);
                  save.mutate({
                    product_id: line.product_id,
                    reason_code: reason,
                    qty_delta: direction === "less" ? `-${parsed}` : parsed,
                  });
                }}
                className={cn(
                  "flex min-h-bouton-principal w-full items-center justify-center gap-2.5 rounded-bouton bg-stock text-[21px] font-bold text-primary-foreground",
                  "outline-none hover:bg-stock/90 focus-visible:ring-3 focus-visible:ring-ring/50",
                  "disabled:cursor-not-allowed disabled:bg-stock/45",
                )}
              >
                <Check className="size-[26px]" aria-hidden />
                {t.submit}
              </button>
            </>
          ) : (
            !loading && <p className="text-muted-foreground">{t.nothing}</p>
          )}
        </section>
      </div>
    </div>
  );
}
