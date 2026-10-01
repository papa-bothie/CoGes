"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { FieldError } from "@/components/field-error";
import { SearchCombobox } from "@/components/search-combobox";
import { Button } from "@/components/ui/button";
import { SegmentedControl } from "@/components/ui/segmented-control";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useCompanyLocale } from "@/hooks/use-me";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage, isApiError } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { queryKeys } from "@/lib/api/queries/keys";
import { useStockFor } from "@/lib/api/queries/stock";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal, parseDecimalInput } from "@/lib/decimal";
import { formatQty } from "@/lib/format";
import { zonedDateTimeIso } from "@/lib/format/zoned";
import { labels } from "@/lib/labels";

type ManualType = Schemas["ManualMovementType"];
type Product = Schemas["ProductRead"];
type Supplier = Schemas["SupplierRead"];

export type MovementProduct = { id: string; name: string; sku: string };

const TYPES: readonly ManualType[] = [
  "purchase_in",
  "initial",
  "adjustment",
  "loss",
  "supplier_return_out",
];
/** Sens imposé par le type ; l'ajustement laisse choisir (règles du schéma d'entrée). */
const OUTFLOWS = new Set<ManualType>(["loss", "supplier_return_out"]);
const COST_REQUIRED = new Set<ManualType>(["initial", "purchase_in"]);
const NOTE_REQUIRED = new Set<ManualType>(["adjustment", "loss"]);
const WITH_SUPPLIER = new Set<ManualType>(["purchase_in", "supplier_return_out"]);

type Errors = Partial<Record<"product" | "qty" | "unitCost" | "note" | "form", string>>;

async function searchProducts(text: string): Promise<Product[]> {
  const page = await unwrap(
    api.GET("/api/v1/products", {
      params: { query: { search: text || undefined, page_size: 8 } },
    }),
  );
  return page.items.filter((product) => product.is_stock_tracked);
}

async function searchSuppliers(text: string): Promise<Supplier[]> {
  const page = await unwrap(
    api.GET("/api/v1/suppliers", {
      params: { query: { search: text || undefined, page_size: 8 } },
    }),
  );
  return page.items;
}

/**
 * Mouvement manuel (réservé au gérant). Le front guide — sens imposé par le type, coût et
 * motif demandés quand la règle les exige — mais c'est le serveur qui tranche, et ses refus
 * (stock insuffisant, antidatage, stock initial déjà saisi…) s'affichent ici.
 */
export function MovementDialog({
  open,
  onOpenChange,
  product: fixedProduct,
  defaultType = "purchase_in",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  product?: MovementProduct;
  defaultType?: ManualType;
}) {
  const queryClient = useQueryClient();
  const { timeZone } = useCompanyLocale();
  const idempotency = useIdempotencyKey();
  const [picked, setPicked] = useState<MovementProduct | null>(null);
  const [type, setType] = useState<ManualType>(defaultType);
  const [direction, setDirection] = useState<"in" | "out">("out");
  const [qty, setQty] = useState("");
  const [unitCost, setUnitCost] = useState("");
  const [supplier, setSupplier] = useState<Supplier | null>(null);
  const [note, setNote] = useState("");
  const [occurredAt, setOccurredAt] = useState("");
  const [errors, setErrors] = useState<Errors>({});

  const product = fixedProduct ?? picked;
  const stock = useStockFor(product ? [product.id] : []);
  const current = product ? stock.data?.get(product.id) : undefined;

  const outflow = type === "adjustment" ? direction === "out" : OUTFLOWS.has(type);
  const showCost = !outflow;
  const costRequired = COST_REQUIRED.has(type);
  const noteRequired = NOTE_REQUIRED.has(type);

  const reset = () => {
    setPicked(null);
    setType(defaultType);
    setDirection("out");
    setQty("");
    setUnitCost("");
    setSupplier(null);
    setNote("");
    setOccurredAt("");
    setErrors({});
  };

  const record = useMutation({
    meta: { toastError: false },
    mutationFn: (body: Schemas["MovementCreate"]) =>
      unwrap(api.POST("/api/v1/inventory/movements", { body, headers: idempotency.headers })),
    onSuccess: () => {
      idempotency.renew();
      for (const key of [
        queryKeys.stock.all,
        queryKeys.movements.all,
        queryKeys.dashboard,
        queryKeys.products.all,
      ]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      toast.success(labels.stock.form.recorded);
      reset();
      onOpenChange(false);
    },
    onError: (error) => {
      if (isApiError(error) && error.code === "insufficient_stock") {
        setErrors({ qty: error.message });
      } else if (isApiError(error) && error.code === "unit_cost_required") {
        setErrors({ unitCost: error.message });
      } else {
        setErrors({ form: errorMessage(error) });
      }
    },
  });

  const submit = () => {
    const next: Errors = {};
    if (!product) next.product = labels.validation.required;
    const parsedQty = parseDecimalInput(qty);
    if (parsedQty === null || compareDecimal(parsedQty, "0") !== 1) {
      next.qty = labels.sales.invalidNumber;
    }
    const parsedCost = unitCost.trim() ? parseDecimalInput(unitCost) : null;
    if (showCost && unitCost.trim() && parsedCost === null)
      next.unitCost = labels.sales.invalidNumber;
    if (showCost && costRequired && !unitCost.trim()) next.unitCost = labels.validation.required;
    if (noteRequired && !note.trim()) next.note = labels.validation.required;
    setErrors(next);
    if (Object.keys(next).length > 0 || !product || parsedQty === null) return;

    record.mutate({
      product_id: product.id,
      type,
      // Le signe dit le sens ; le serveur vérifie qu'il concorde avec le type.
      qty_delta: outflow ? `-${parsedQty}` : parsedQty,
      unit_cost: showCost ? parsedCost : null,
      supplier_id: WITH_SUPPLIER.has(type) ? (supplier?.id ?? null) : null,
      note: note.trim() || null,
      occurred_at: occurredAt ? zonedDateTimeIso(occurredAt, timeZone) : null,
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
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{labels.stock.form.title}</DialogTitle>
          {product && current && (
            <DialogDescription>
              {labels.stock.form.currentStock(formatQty(current.qty_on_hand))}
            </DialogDescription>
          )}
        </DialogHeader>
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <div className="space-y-1.5">
            <Label>{labels.stock.form.product}</Label>
            {product ? (
              <div className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2">
                <span>
                  <span className="font-medium">{product.name}</span>{" "}
                  <span className="text-xs numeric text-muted-foreground">{product.sku}</span>
                </span>
                {!fixedProduct && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={labels.stock.journal.clearProduct}
                    onClick={() => setPicked(null)}
                  >
                    <X />
                  </Button>
                )}
              </div>
            ) : (
              <SearchCombobox
                label={labels.stock.form.productSearch}
                queryKey={[...queryKeys.products.search, "tracked"]}
                search={searchProducts}
                itemKey={(item) => item.id}
                onSelect={(item) => setPicked({ id: item.id, name: item.name, sku: item.sku })}
                renderItem={(item) => (
                  <span className="flex justify-between gap-3">
                    <span>{item.name}</span>
                    <span className="numeric text-muted-foreground">{item.sku}</span>
                  </span>
                )}
              />
            )}
            <FieldError message={errors.product} />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="movement-type">{labels.stock.form.type}</Label>
              <Select value={type} onValueChange={(value) => setType(value as ManualType)}>
                <SelectTrigger id="movement-type" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TYPES.map((value) => (
                    <SelectItem key={value} value={value}>
                      {labels.stock.movementTypes[value]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {type === "adjustment" && (
              <div className="space-y-1.5">
                <Label id="direction-label">{labels.stock.form.direction}</Label>
                <SegmentedControl
                  aria-labelledby="direction-label"
                  value={direction}
                  onValueChange={setDirection}
                  options={[
                    { value: "in", label: labels.stock.form.increase },
                    { value: "out", label: labels.stock.form.decrease },
                  ]}
                  className="grid w-full"
                  itemClassName="px-2"
                />
              </div>
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="movement-qty">{labels.stock.form.qty}</Label>
              <Input
                id="movement-qty"
                inputMode="decimal"
                value={qty}
                aria-invalid={Boolean(errors.qty)}
                onChange={(event) => setQty(event.target.value)}
                className="h-9 text-right numeric"
              />
              <FieldError message={errors.qty} />
            </div>
            {showCost && (
              <div className="space-y-1.5">
                <Label htmlFor="movement-cost">
                  {costRequired ? labels.stock.form.unitCost : labels.stock.form.unitCostOptional}
                </Label>
                <Input
                  id="movement-cost"
                  inputMode="decimal"
                  value={unitCost}
                  aria-invalid={Boolean(errors.unitCost)}
                  onChange={(event) => setUnitCost(event.target.value)}
                  className="h-9 text-right numeric"
                />
                <FieldError message={errors.unitCost} />
              </div>
            )}
          </div>

          {WITH_SUPPLIER.has(type) && (
            <div className="space-y-1.5">
              <Label>{labels.stock.form.supplier}</Label>
              {supplier ? (
                <div className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2">
                  <span className="font-medium">{supplier.name}</span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={labels.stock.form.removeSupplier}
                    onClick={() => setSupplier(null)}
                  >
                    <X />
                  </Button>
                </div>
              ) : (
                <SearchCombobox
                  label={labels.stock.form.supplierSearch}
                  queryKey={["suppliers", "search"]}
                  search={searchSuppliers}
                  itemKey={(item) => item.id}
                  onSelect={setSupplier}
                  renderItem={(item) => item.name}
                />
              )}
            </div>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="movement-note">
              {noteRequired ? labels.stock.form.noteRequired : labels.stock.form.note}
            </Label>
            <Textarea
              id="movement-note"
              value={note}
              maxLength={500}
              aria-invalid={Boolean(errors.note)}
              onChange={(event) => setNote(event.target.value)}
            />
            <FieldError message={errors.note} />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="movement-date">{labels.stock.form.occurredAt}</Label>
            <Input
              id="movement-date"
              type="datetime-local"
              value={occurredAt}
              onChange={(event) => setOccurredAt(event.target.value)}
              className="h-9"
            />
          </div>

          <FieldError message={errors.form} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {labels.common.close}
            </Button>
            <Button type="submit" disabled={record.isPending}>
              {record.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {labels.stock.form.submit}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
