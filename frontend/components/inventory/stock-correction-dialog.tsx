"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarX,
  Gift,
  Hammer,
  House,
  Loader2,
  Minus,
  Plus,
  Search,
  ShieldAlert,
  Sigma,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { FieldError } from "@/components/field-error";
import { ChoiceTiles } from "@/components/kit/choice-tile";
import { ProductSquare } from "@/components/kit/list-row";
import { QuantityStepper } from "@/components/kit/quantity-stepper";
import { fieldClasses, RUBRIQUE_CLASSES } from "@/components/kit/rubrique";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal, parseDecimalInput, subtractDecimal } from "@/lib/decimal";
import { formatQtyWithUnit } from "@/lib/format/qty";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

type StockLine = Schemas["StockLine"];
type Reason = Schemas["StockReason"];
type Direction = "more" | "less";

/** Raisons de la maquette 10, dans son ordre (ADR 0067). */
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

function quantity(line: Pick<StockLine, "unit">, value: string): string {
  return formatQtyWithUnit(value, labels.units[line.unit], labels.unitsPlural[line.unit]);
}

/**
 * « Corriger le stock » (maquette 10) : l'article, ce que le logiciel compte, Plus ou Moins
 * dans la boutique, combien, et pourquoi en tuiles — jamais au clavier. Le type du
 * mouvement se déduit de la raison côté serveur, le coût est le CMP courant et la date
 * « maintenant » (ADR 0067). Réservé au gérant (`inventory:create`).
 */
export function StockCorrectionDialog({
  open,
  onOpenChange,
  productId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Ouvert depuis une fiche article : la liste est sautée. */
  productId?: string;
}) {
  const queryClient = useQueryClient();
  const idempotency = useIdempotencyKey();
  const [pickedId, setPickedId] = useState<string | undefined>(productId);
  const [search, setSearch] = useState("");
  const [direction, setDirection] = useState<Direction>("less");
  const [qty, setQty] = useState("1");
  const [reason, setReason] = useState<Reason | undefined>(undefined);
  const [formError, setFormError] = useState<string | null>(null);
  const t = labels.stock.correction;

  // Ruptures et seuils bas en tête : l'ordre du serveur (ADR 0012).
  const params = { page_size: 100, ...(productId ? { product_id: [productId] } : {}) };
  const stock = useQuery({
    queryKey: queryKeys.stock.list(params),
    queryFn: () => unwrap(api.GET("/api/v1/inventory/stock", { params: { query: params } })),
    enabled: open,
  });
  // Une recherche interroge le serveur : la boutique peut compter plus de 100 articles.
  const needle = search.trim();
  const found = useQuery({
    queryKey: [...queryKeys.stock.all, "correction", needle],
    enabled: open && needle.length > 0,
    queryFn: async () => {
      const products = await unwrap(
        api.GET("/api/v1/products", { params: { query: { search: needle, page_size: 20 } } }),
      );
      const ids = products.items.map((product) => product.id);
      if (ids.length === 0) return [];
      const page = await unwrap(
        api.GET("/api/v1/inventory/stock", {
          params: { query: { product_id: ids, page_size: 100 } },
        }),
      );
      return page.items;
    },
  });
  const lines = needle ? (found.data ?? []) : (stock.data?.items ?? []);
  const line =
    lines.find((item) => item.product_id === pickedId) ??
    stock.data?.items.find((item) => item.product_id === pickedId);
  const shown = lines;

  const parsed = parseDecimalInput(qty);
  const positive = parsed !== null && compareDecimal(parsed, "0") === 1;
  const after =
    line && parsed !== null
      ? subtractDecimal(line.qty_on_hand, direction === "less" ? parsed : `-${parsed}`)
      : null;
  const tooMany = after !== null && compareDecimal(after, "0") === -1;
  const ready = Boolean(line) && positive && !tooMany && Boolean(reason);

  const reset = () => {
    setPickedId(productId);
    setSearch("");
    setDirection("less");
    setQty("1");
    setReason(undefined);
    setFormError(null);
  };

  const save = useMutation({
    meta: { toastError: false },
    mutationFn: (body: Schemas["MovementCreate"]) =>
      unwrap(api.POST("/api/v1/inventory/movements", { body, headers: idempotency.headers })),
    onSuccess: () => {
      idempotency.renew();
      for (const key of [queryKeys.stock.all, queryKeys.products.all, queryKeys.movements.all]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      toast.success(t.done);
      reset();
      onOpenChange(false);
    },
    onError: (error) => setFormError(errorMessage(error)),
  });

  const submit = () => {
    if (!line || !ready || parsed === null || !reason) return;
    setFormError(null);
    save.mutate({
      product_id: line.product_id,
      reason_code: reason,
      qty_delta: direction === "less" ? `-${parsed}` : parsed,
    });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t.title}</DialogTitle>
        </DialogHeader>

        {!line ? (
          <section className="space-y-3">
            <p className="text-libelle">{t.whichProduct}</p>
            <input
              aria-label={t.search}
              placeholder={t.search}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className={cn(fieldClasses("stock"), "min-h-cible px-4 text-corps")}
            />
            {(needle ? found.isPending : stock.isPending) ? (
              <Skeleton className="h-40 w-full" />
            ) : (
              <ul className="max-h-[50vh] space-y-2 overflow-y-auto">
                {shown.map((item) => {
                  const low = item.status !== "ok";
                  return (
                    <li key={item.product_id}>
                      <button
                        type="button"
                        onClick={() => setPickedId(item.product_id)}
                        className={cn(
                          "flex min-h-16 w-full items-center gap-3 rounded-tuile border-2 px-3 text-left",
                          "outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50",
                          low ? "border-stock/40 bg-stock-teinte" : "border-input bg-card",
                        )}
                      >
                        <ProductSquare name={item.name} />
                        <span className="min-w-0 flex-1 truncate text-libelle">{item.name}</span>
                        <span
                          className={cn(
                            "text-corps font-bold numeric",
                            low ? "text-stock-encre" : "text-muted-foreground",
                          )}
                        >
                          {item.status === "out"
                            ? t.out
                            : low
                              ? t.left(quantity(item, item.qty_on_hand))
                              : quantity(item, item.qty_on_hand)}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        ) : (
          <form
            noValidate
            className="space-y-5"
            onSubmit={(event) => {
              event.preventDefault();
              submit();
            }}
          >
            <div className="flex items-center gap-3 rounded-carte border-2 border-input bg-card p-4">
              <ProductSquare name={line.name} size="grand" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-titre-carte">{line.name}</p>
                <p className="text-corps text-muted-foreground">
                  {t.counts}{" "}
                  <span className="font-extrabold numeric text-foreground">
                    {quantity(line, line.qty_on_hand)}
                  </span>
                </p>
              </div>
              {!productId && (
                <Button type="button" variant="ghost" onClick={() => setPickedId(undefined)}>
                  {t.change}
                </Button>
              )}
            </div>

            <div className="space-y-2">
              <p className="text-libelle">{t.inShop}</p>
              <div role="radiogroup" aria-label={t.inShop} className="grid grid-cols-2 gap-2.5">
                {(["more", "less"] as const).map((value) => {
                  const Icon = value === "more" ? Plus : Minus;
                  const picked = direction === value;
                  return (
                    <button
                      key={value}
                      type="button"
                      role="radio"
                      aria-checked={picked}
                      onClick={() => {
                        setDirection(value);
                        setReason(undefined);
                      }}
                      className={cn(
                        "flex min-h-bouton items-center justify-center gap-2 rounded-bouton border-2 text-libelle",
                        "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                        picked
                          ? RUBRIQUE_CLASSES.stock.solid
                          : "border-input bg-card text-foreground hover:bg-voile",
                      )}
                    >
                      <Icon className="size-6" aria-hidden />
                      {value === "more" ? t.more : t.less}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="space-y-2">
              <p className="text-libelle">{t.howMany}</p>
              <div className="flex flex-wrap items-center gap-4">
                <QuantityStepper
                  value={qty}
                  onChange={setQty}
                  itemName={line.name}
                  min={0}
                  rubrique="stock"
                  size="grand"
                />
                {after !== null && !tooMany && (
                  <p className="text-libelle" role="status">
                    {t.after}{" "}
                    <span className="text-chiffre numeric text-stock-encre">
                      {quantity(line, after)}
                    </span>
                  </p>
                )}
              </div>
              {tooMany && <FieldError message={t.tooMany(quantity(line, line.qty_on_hand))} />}
            </div>

            <div className="space-y-2">
              <p className="text-libelle">{t.why}</p>
              <ChoiceTiles
                label={t.why}
                value={reason}
                onValueChange={setReason}
                rubrique="stock"
                choices={REASONS[direction].map((choice) => ({
                  value: choice.value,
                  label: labels.stock.reasons[choice.value],
                  icon: choice.icon,
                }))}
              />
            </div>

            <FieldError message={formError} />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                {labels.common.close}
              </Button>
              <Button
                type="submit"
                variant="stock"
                size="standard"
                disabled={!ready || save.isPending}
              >
                {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
                {t.submit}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
