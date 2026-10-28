"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Loader2, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useId, useMemo, useState } from "react";
import { toast } from "sonner";

import { DraftBanner } from "@/components/draft-banner";
import { FieldError } from "@/components/field-error";
import { cleanAmount } from "@/components/kit/amount-field";
import { Chip } from "@/components/kit/chip";
import { FieldHint } from "@/components/kit/feedback";
import { QuantityStepper } from "@/components/kit/quantity-stepper";
import { fieldClasses } from "@/components/kit/rubrique";
import { BarcodeScanButton } from "@/components/products/barcode-scanner";
import { Button } from "@/components/ui/button";
import { useDraft } from "@/hooks/use-draft";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { flattenTree, useCategories } from "@/lib/api/queries/categories";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal, parseDecimalInput } from "@/lib/decimal";
import { draftOneOf, draftString } from "@/lib/drafts";
import { formatAmount } from "@/lib/format/money";
import { labels } from "@/lib/labels";
import { typedAmount } from "@/lib/payment-amount";
import { qtyWithUnit } from "@/lib/units";
import { cn } from "@/lib/utils";

type Unit = Schemas["ProductUnit"];

/** « Vendu par » de la maquette 09, dans son ordre. Le mètre reste sur la fiche. */
const UNITS: readonly Unit[] = ["piece", "sac", "kg", "litre", "carton", "paquet", "bouteille"];

/** Brouillon de « Nouvel article » (ADR 0101). Le rayon est revérifié par le serveur à l'envoi. */
const DRAFT = {
  formId: "product-new",
  version: 1,
  fields: ["name", "price", "cost", "unit", "categoryId", "qty", "warnAt", "barcode"],
  meaningful: ["name", "price", "cost", "qty", "warnAt", "barcode"],
} as const;

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
 * et le code-barres sont générés par le serveur (ADR 0066), la TVA est celle des réglages, le
 * stock toujours suivi. L'article et son stock d'ouverture naissent ensemble
 * (`POST /inventory/products`).
 */
export function NewProductForm() {
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
  const [done, setDone] = useState<{ name: string; stock: string; price: string } | null>(null);
  const draft = useDraft(
    DRAFT,
    {
      name,
      price,
      cost,
      unit,
      categoryId: categoryId ?? "",
      // Le stock d'ouverture « 0 » est l'état de départ, pas une saisie.
      qty: qty === "0" ? "" : qty,
      warnAt,
      barcode: barcode ?? "",
    },
    (fields) => {
      setName(draftString(fields.name) ?? "");
      setPrice(draftString(fields.price) ?? "");
      setCost(draftString(fields.cost) ?? "");
      setUnit(draftOneOf(fields.unit, UNITS) ?? "piece");
      setCategoryId(draftString(fields.categoryId) || null);
      setQty(draftString(fields.qty) || "0");
      setWarnAt(draftString(fields.warnAt) ?? "");
      setBarcode(draftString(fields.barcode) || null);
    },
  );

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
      draft.clear();
      toast.success(t.created);
      setDone({
        name: created.product.name,
        stock: qtyWithUnit(opening ?? "0", created.product.unit),
        price: formatAmount(created.product.unit_price, currency),
      });
    },
    onError: (error) => setFormError(errorMessage(error)),
  });

  const onScan = useCallback((code: string) => setBarcode(code), []);

  const again = () => {
    setDone(null);
    setName("");
    setPrice("");
    setCost("");
    setQty("0");
    setWarnAt("");
    setBarcode(null);
  };

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
      // Toujours suivi ; TVA nulle = celle des réglages de l'entreprise (ADR 0066). La
      // fiche les change dans « Plus d'infos ».
      is_stock_tracked: true,
      default_tax_rate: null,
      opening_qty: opening,
      reorder_point: warnAt.trim() ? parseDecimalInput(warnAt) : null,
    });
  };

  const field = cn(fieldClasses("stock"), "min-h-[58px] px-4 text-[19px]");

  return (
    <div className="mx-auto flex max-w-[772px] flex-col gap-5">
      <Link
        href="/products"
        className="inline-flex min-h-11 items-center gap-2 self-start font-bold text-ventes hover:text-ventes-encre pointer-coarse:min-h-12"
      >
        <ArrowLeft className="size-[22px]" aria-hidden />
        {t.back}
      </Link>
      <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{t.title}</h1>

      {done ? (
        <section
          aria-live="polite"
          className="flex flex-col items-center gap-3 rounded-carte border border-border bg-card px-6 py-10 text-center"
        >
          <span
            aria-hidden
            className="flex size-20 items-center justify-center rounded-full bg-stock text-primary-foreground"
          >
            <Check className="size-11" strokeWidth={2.5} />
          </span>
          <h2 className="text-[28px] leading-tight font-extrabold">{t.done(done.name)}</h2>
          <p className="text-lg text-muted-foreground">{t.doneDetail(done.stock, done.price)}</p>
          <div className="mt-2.5 flex flex-wrap justify-center gap-3">
            <Button type="button" variant="stock" size="standard" onClick={again}>
              {t.another}
            </Button>
            <Button asChild variant="secondaire" size="standard">
              <Link href="/sales/new">{t.goSell}</Link>
            </Button>
          </div>
        </section>
      ) : (
        <form
          noValidate
          className="flex flex-col gap-6 rounded-carte border border-border bg-card p-carte"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          {draft.restored && (
            <DraftBanner
              onClear={() => {
                again();
                setUnit("piece");
                setCategoryId(null);
                draft.clear();
              }}
            />
          )}
          <div className="flex flex-wrap items-center gap-3">
            <BarcodeScanButton onScan={onScan} tile />
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

          <div>
            <label htmlFor={nameId} className="mb-2 block text-libelle">
              {t.name}
            </label>
            <input
              id={nameId}
              value={name}
              maxLength={200}
              autoComplete="off"
              onChange={(event) => setName(event.target.value)}
              className={field}
            />
          </div>

          <div className="space-y-6">
            <div className="flex flex-wrap gap-4">
              <div className="flex-[1_1_220px]">
                <label htmlFor={`${nameId}-prix`} className="mb-2 block text-libelle">
                  {t.price}
                </label>
                <input
                  id={`${nameId}-prix`}
                  inputMode="numeric"
                  autoComplete="off"
                  value={price}
                  onChange={(event) => setPrice(cleanAmount(event.target.value))}
                  className={cn(field, "numeric")}
                />
              </div>
              <div className="flex-[1_1_220px]">
                <label htmlFor={`${nameId}-achat`} className="mb-2 block text-libelle">
                  {t.cost}
                </label>
                <input
                  id={`${nameId}-achat`}
                  inputMode="numeric"
                  autoComplete="off"
                  value={cost}
                  onChange={(event) => setCost(cleanAmount(event.target.value))}
                  className={cn(field, "numeric")}
                />
              </div>
            </div>
            <p
              role="status"
              className={cn(
                "rounded-champ px-[18px] py-3.5 text-lg font-bold",
                margin.tone === "gain"
                  ? "bg-ventes-teinte text-ventes-encre"
                  : "bg-stock-teinte text-stock-encre",
              )}
            >
              {margin.text}
            </p>
          </div>

          <div>
            <p className="mb-2 text-libelle">{t.soldBy}</p>
            <div role="group" aria-label={t.soldBy} className="flex flex-wrap gap-2">
              {UNITS.map((value) => (
                <Chip
                  key={value}
                  rubrique="stock"
                  className="min-h-[50px] font-semibold"
                  selected={unit === value}
                  onClick={() => setUnit(value)}
                >
                  {labels.products.unitChips[value]}
                </Chip>
              ))}
            </div>
          </div>

          <div>
            <p className="mb-2 text-libelle">{t.shelf}</p>
            <div role="group" aria-label={t.shelf} className="flex flex-wrap gap-2">
              {shelves.map((shelf) => (
                <Chip
                  key={shelf.id}
                  rubrique="stock"
                  className="min-h-[50px] font-semibold"
                  selected={categoryId === shelf.id}
                  onClick={() => setCategoryId(categoryId === shelf.id ? null : shelf.id)}
                >
                  {shelf.name}
                </Chip>
              ))}
              {canAddShelf && newShelf === null && (
                <Chip
                  rubrique="stock"
                  className="min-h-[50px] border-dashed font-semibold"
                  onClick={() => setNewShelf("")}
                >
                  {t.newShelf}
                </Chip>
              )}
            </div>
            {newShelf !== null && (
              <div className="mt-2.5 flex flex-wrap items-end gap-2.5">
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

          <div className="flex flex-wrap gap-6">
            <div className="flex-[1_1_260px]">
              <p className="mb-2 text-libelle">{t.howMany}</p>
              <QuantityStepper
                value={qty}
                onChange={setQty}
                itemName={name.trim() || t.thisArticle}
                inputLabel={t.howManyField}
                rubrique="stock"
                size="grand"
              />
              {costMissing && <FieldHint rubrique="stock">{t.costForStock}</FieldHint>}
            </div>
            <div className="flex-[1_1_260px]">
              <p className="mb-2 text-libelle">{t.warnAt}</p>
              <QuantityStepper
                value={warnAt}
                onChange={setWarnAt}
                itemName={name.trim() || t.thisArticle}
                inputLabel={t.warnAtField}
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
            className="w-full text-[21px] font-bold disabled:bg-stock/45 disabled:opacity-100"
            disabled={!ready || save.isPending}
          >
            {save.isPending ? (
              <Loader2 className="size-[26px] animate-spin" aria-hidden />
            ) : (
              <Check className="size-[26px]" aria-hidden />
            )}
            {t.submit}
          </Button>
        </form>
      )}
    </div>
  );
}
