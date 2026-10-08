"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useId, useMemo, useState } from "react";
import { toast } from "sonner";

import { FieldError } from "@/components/field-error";
import { AmountField } from "@/components/kit/amount-field";
import { Chip } from "@/components/kit/chip";
import { FieldHint } from "@/components/kit/feedback";
import { QuantityStepper } from "@/components/kit/quantity-stepper";
import { fieldClasses } from "@/components/kit/rubrique";
import { BarcodeScanButton } from "@/components/products/barcode-scanner";
import { Button } from "@/components/ui/button";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { flattenTree, useCategories } from "@/lib/api/queries/categories";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal, parseDecimalInput } from "@/lib/decimal";
import { formatAmount } from "@/lib/format/money";
import { labels } from "@/lib/labels";
import { typedAmount } from "@/lib/payment-amount";
import { cn } from "@/lib/utils";

type Unit = Schemas["ProductUnit"];

/** « Vendu par » de la maquette 09, dans son ordre. Le mètre reste sur la fiche. */
const UNITS: readonly Unit[] = ["piece", "sac", "kg", "litre", "carton", "paquet", "bouteille"];

/** Ligne en direct sous les prix (maquette 09) : ce qu'on gagne, ou ce qu'on perd. */
export function marginLine(
  price: string,
  cost: string,
  unit: Unit,
  currency: string,
): { text: string; tone: "gain" | "perte" | "neutre" } {
  const sell = typedAmount(price);
  const buy = typedAmount(cost);
  const t = labels.products.newForm;
  if (sell === 0n || buy === 0n) return { text: t.bothPrices, tone: "neutre" };
  const gain = sell - buy;
  if (gain > 0n) {
    return {
      text: t.gain(formatAmount(gain.toString(), currency), labels.units[unit]),
      tone: "gain",
    };
  }
  if (gain === 0n) return { text: t.noGain, tone: "neutre" };
  return { text: t.loss(formatAmount((-gain).toString(), currency)), tone: "perte" };
}

/**
 * Nouvel article (lot 1, maquette 09) : seulement ce que le commerçant sait. La référence
 * et le code-barres sont générés par le serveur (ADR 0066), la TVA est celle par défaut, le
 * stock toujours suivi. L'article et son stock d'ouverture naissent ensemble
 * (`POST /inventory/products`).
 */
export function NewProductForm() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { currency } = useCompanyLocale();
  const categories = useCategories();
  const canAddShelf = usePermission("categories:create");
  const shelves = useMemo(() => flattenTree(categories.data ?? []), [categories.data]);
  const nameId = useId();
  const shelfId = useId();
  const t = labels.products.newForm;

  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [cost, setCost] = useState("");
  const [unit, setUnit] = useState<Unit>("piece");
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [newShelf, setNewShelf] = useState<string | null>(null);
  const [qty, setQty] = useState("0");
  const [warnAt, setWarnAt] = useState("");
  const [barcode, setBarcode] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const opening = parseDecimalInput(qty || "0");
  const hasStock = opening !== null && compareDecimal(opening, "0") === 1;
  const costMissing = hasStock && typedAmount(cost) === 0n;
  const ready =
    name.trim().length > 0 && typedAmount(price) > 0n && opening !== null && !costMissing;
  const margin = marginLine(price, cost, unit, currency);

  const addShelf = useMutation({
    meta: { toastError: false },
    mutationFn: (shelf: string) =>
      unwrap(api.POST("/api/v1/categories", { body: { name: shelf } })),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.categories.all });
      setCategoryId(created.id);
      setNewShelf(null);
    },
    onError: (error) => setFormError(errorMessage(error)),
  });

  const save = useMutation({
    meta: { toastError: false },
    mutationFn: (body: Schemas["NewProductCreate"]) =>
      unwrap(api.POST("/api/v1/inventory/products", { body })),
    onSuccess: (created) => {
      for (const key of [queryKeys.products.all, queryKeys.stock.all]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      toast.success(t.created);
      router.push(`/products/${created.product.id}`);
    },
    onError: (error) => setFormError(errorMessage(error)),
  });

  const onScan = useCallback((code: string) => setBarcode(code), []);

  const submit = () => {
    if (!ready || opening === null) return;
    setFormError(null);
    save.mutate({
      name: name.trim(),
      unit,
      unit_price: price,
      cost_price: typedAmount(cost) > 0n ? cost : null,
      category_id: categoryId,
      barcode,
      // Toujours suivi, TVA par défaut (0) : la fiche les change dans « Plus d'infos ».
      is_stock_tracked: true,
      default_tax_rate: "0",
      opening_qty: opening,
      reorder_point: warnAt.trim() ? parseDecimalInput(warnAt) : null,
    });
  };

  return (
    <form
      noValidate
      className="mx-auto max-w-[820px] space-y-6"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div className="flex flex-wrap items-center gap-3">
        <BarcodeScanButton onScan={onScan} />
        {barcode && (
          <span className="inline-flex items-center gap-2 rounded-full bg-stock-teinte px-4 py-2 text-corps font-bold numeric text-stock-encre">
            {t.scanned(barcode)}
            <button
              type="button"
              aria-label={t.removeCode}
              onClick={() => setBarcode(null)}
              className="rounded-full p-1 outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <X className="size-4" aria-hidden />
            </button>
          </span>
        )}
      </div>

      <div className="space-y-2">
        <label htmlFor={nameId} className="block text-libelle">
          {t.name}
        </label>
        <input
          id={nameId}
          value={name}
          maxLength={200}
          autoComplete="off"
          onChange={(event) => setName(event.target.value)}
          className={cn(fieldClasses("stock"), "min-h-bouton px-[18px] text-xl font-semibold")}
        />
      </div>

      <div className="space-y-2">
        <div className="grid gap-4 sm:grid-cols-2">
          <AmountField label={t.price} value={price} onChange={setPrice} rubrique="stock" />
          <AmountField label={t.cost} value={cost} onChange={setCost} rubrique="stock" />
        </div>
        <p
          role="status"
          className={cn(
            "rounded-champ px-4 py-3 text-corps font-bold",
            margin.tone === "gain"
              ? "bg-ventes-teinte text-ventes-encre"
              : margin.tone === "perte"
                ? "bg-stock-teinte text-stock-encre"
                : "bg-muted text-foreground",
          )}
        >
          {margin.text}
        </p>
      </div>

      <div className="space-y-2">
        <p className="text-libelle">{t.soldBy}</p>
        <div role="group" aria-label={t.soldBy} className="flex flex-wrap gap-2.5">
          {UNITS.map((value) => (
            <Chip
              key={value}
              rubrique="stock"
              selected={unit === value}
              onClick={() => setUnit(value)}
            >
              {labels.products.unitChips[value]}
            </Chip>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <p className="text-libelle">{t.shelf}</p>
        <div role="group" aria-label={t.shelf} className="flex flex-wrap gap-2.5">
          {shelves.map((shelf) => (
            <Chip
              key={shelf.id}
              rubrique="stock"
              selected={categoryId === shelf.id}
              onClick={() => setCategoryId(categoryId === shelf.id ? null : shelf.id)}
            >
              {shelf.name}
            </Chip>
          ))}
          {canAddShelf && newShelf === null && (
            <Chip rubrique="stock" onClick={() => setNewShelf("")}>
              {t.newShelf}
            </Chip>
          )}
        </div>
        {newShelf !== null && (
          <div className="flex flex-wrap items-end gap-2.5">
            <div className="min-w-60 flex-1 space-y-1.5">
              <label htmlFor={shelfId} className="block text-petit font-bold">
                {t.newShelfName}
              </label>
              <input
                id={shelfId}
                autoFocus
                value={newShelf}
                maxLength={120}
                onChange={(event) => setNewShelf(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    if (newShelf.trim()) addShelf.mutate(newShelf.trim());
                  }
                }}
                className={cn(fieldClasses("stock"), "min-h-cible px-4 text-corps")}
              />
            </div>
            <Button
              type="button"
              variant="secondaire"
              disabled={!newShelf.trim() || addShelf.isPending}
              onClick={() => addShelf.mutate(newShelf.trim())}
            >
              {t.addShelf}
            </Button>
          </div>
        )}
      </div>

      <div className="grid gap-6 sm:grid-cols-2">
        <div className="space-y-2">
          <p className="text-libelle">{t.howMany}</p>
          <QuantityStepper
            value={qty}
            onChange={setQty}
            itemName={name.trim() || t.thisArticle}
            rubrique="stock"
            size="grand"
          />
          {costMissing && <FieldHint rubrique="stock">{t.costForStock}</FieldHint>}
        </div>
        <div className="space-y-2">
          <p className="text-libelle">{t.warnAt}</p>
          <QuantityStepper
            value={warnAt}
            onChange={setWarnAt}
            itemName={name.trim() || t.thisArticle}
            rubrique="stock"
            size="grand"
          />
        </div>
      </div>

      <FieldError message={formError} />
      <Button
        type="submit"
        variant="stock"
        size="principal"
        className="w-full"
        disabled={!ready || save.isPending}
      >
        {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
        {t.submit}
      </Button>
    </form>
  );
}
