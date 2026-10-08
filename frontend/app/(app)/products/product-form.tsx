"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState, type ReactNode } from "react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { FieldError } from "@/components/field-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage, isApiError } from "@/lib/api/errors";
import { flattenTree, useCategories } from "@/lib/api/queries/categories";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import {
  compareDecimal,
  parseDecimalInput,
  percentToRate,
  rateToPercent,
  toInputDecimal,
} from "@/lib/decimal";
import { labels } from "@/lib/labels";

type Product = Schemas["ProductRead"];
type Unit = Schemas["ProductUnit"];

const UNITS: readonly Unit[] = [
  "piece",
  "sac",
  "kg",
  "litre",
  "carton",
  "paquet",
  "bouteille",
  "metre",
];
const NONE = "none";

const decimal = (message: string) =>
  z.string().refine((value) => parseDecimalInput(value) !== null, message);
const optionalDecimal = (message: string) =>
  z.string().refine((value) => !value.trim() || parseDecimalInput(value) !== null, message);

/** Bornes reprises des schémas d'entrée de l'API ; le serveur revalide de toute façon. */
const schema = z.object({
  name: z.string().trim().min(1, labels.validation.required).max(200),
  sku: z.string().trim().min(1, labels.validation.required).max(64),
  barcode: z.string().trim().max(64),
  category_id: z.string(),
  unit: z.enum(UNITS),
  is_stock_tracked: z.boolean(),
  is_active: z.boolean(),
  tax_percent: decimal(labels.sales.invalidNumber).refine((value) => {
    const rate = percentToRate(value);
    // Borne de l'API : 0 ≤ taux < 1 (moins de 100 %).
    return rate !== null && compareDecimal(rate, "1") === -1;
  }, labels.sales.invalidNumber),
  reorder_point: optionalDecimal(labels.sales.invalidNumber),
});
type Values = z.infer<typeof schema>;

/** Erreurs métier renvoyées sur un champ précis. */
const FIELD_CODES: Record<string, keyof Values> = {
  product_sku_taken: "sku",
  product_barcode_taken: "barcode",
};

/**
 * Modification d'un article. La création a son formulaire court (`new/new-product-form`,
 * lot 1) ; le prix se change depuis la fiche, chaque changement étant historisé (ADR 0011).
 * Référence, code-barres, TVA, suivi et état attendent dans « Plus d'infos », fermé.
 */
export function ProductForm({ product }: { product: Product }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const categories = useCategories();
  const tree = useMemo(() => flattenTree(categories.data ?? []), [categories.data]);
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    control,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: product.name,
      sku: product.sku,
      barcode: product.barcode ?? "",
      category_id: product.category_id ?? NONE,
      unit: product.unit,
      is_stock_tracked: product.is_stock_tracked,
      is_active: product.is_active,
      tax_percent: rateToPercent(product.default_tax_rate),
      reorder_point: product.reorder_point ? toInputDecimal(product.reorder_point) : "",
    },
  });

  const save = useMutation({
    meta: { toastError: false },
    mutationFn: async (values: Values) => {
      const common = {
        name: values.name,
        sku: values.sku,
        unit: values.unit,
        barcode: values.barcode || null,
        category_id: values.category_id === NONE ? null : values.category_id,
        is_stock_tracked: values.is_stock_tracked,
        default_tax_rate: percentToRate(values.tax_percent) ?? "0",
        reorder_point: values.reorder_point.trim() ? parseDecimalInput(values.reorder_point) : null,
      };
      return unwrap(
        api.PATCH("/api/v1/products/{product_id}", {
          params: { path: { product_id: product.id } },
          body: { ...common, is_active: values.is_active },
        }),
      );
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.products.detail(saved.id), saved);
      for (const key of [queryKeys.products.all, queryKeys.stock.all]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      toast.success(labels.products.saved);
      router.push(`/products/${saved.id}`);
    },
    onError: (error) => {
      if (isApiError(error)) {
        const field = FIELD_CODES[error.code];
        if (field) {
          setError(field, { message: error.message });
          return;
        }
        if (error.status === 422) {
          for (const name of Object.keys(error.fieldErrors())) {
            if (name in schema.shape) {
              setError(name as keyof Values, { message: labels.validation.invalidValue });
            }
          }
        }
      }
      setFormError(errorMessage(error));
    },
  });

  return (
    <form
      noValidate
      className="space-y-6"
      onSubmit={handleSubmit((values) => {
        setFormError(null);
        save.mutate(values);
      })}
    >
      <Card>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field id="name" label={labels.products.name} error={errors.name?.message} wide>
            <Input id="name" aria-invalid={Boolean(errors.name)} {...register("name")} />
          </Field>
          <Field id="category" label={labels.products.category}>
            <Controller
              control={control}
              name="category_id"
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="category" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>{labels.products.noCategory}</SelectItem>
                    {tree.map((node) => (
                      <SelectItem key={node.id} value={node.id}>
                        <span style={{ paddingLeft: `${node.depth * 12}px` }}>{node.name}</span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
          </Field>
          <Field id="unit" label={labels.products.unit}>
            <Controller
              control={control}
              name="unit"
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="unit" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {UNITS.map((unit) => (
                      <SelectItem key={unit} value={unit}>
                        {labels.units[unit]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
          </Field>
          <Field
            id="reorder"
            label={labels.products.reorderLabel}
            error={errors.reorder_point?.message}
          >
            <Input
              id="reorder"
              inputMode="decimal"
              aria-invalid={Boolean(errors.reorder_point)}
              className="text-right numeric"
              {...register("reorder_point")}
            />
          </Field>
          <details
            className="rounded-champ border-2 border-input px-4 py-3 sm:col-span-2"
            open={Boolean(errors.sku || errors.barcode || errors.tax_percent) || undefined}
          >
            <summary className="min-h-cible cursor-pointer content-center text-libelle">
              {labels.products.moreInfo}
            </summary>
            <div className="grid gap-4 pt-3 sm:grid-cols-2">
              <Field id="sku" label={labels.products.sku} error={errors.sku?.message}>
                <Input id="sku" aria-invalid={Boolean(errors.sku)} {...register("sku")} />
              </Field>
              <Field id="barcode" label={labels.products.barcode} error={errors.barcode?.message}>
                <Input
                  id="barcode"
                  aria-invalid={Boolean(errors.barcode)}
                  {...register("barcode")}
                />
              </Field>
              <Field
                id="tax"
                label={labels.products.taxPercent}
                error={errors.tax_percent?.message}
              >
                <Input
                  id="tax"
                  inputMode="decimal"
                  aria-invalid={Boolean(errors.tax_percent)}
                  className="text-right numeric"
                  {...register("tax_percent")}
                />
              </Field>
              <label className="flex items-center gap-2 text-sm sm:col-span-2">
                <input
                  type="checkbox"
                  className="size-4 accent-primary"
                  {...register("is_stock_tracked")}
                />
                {labels.products.trackedLabel}
              </label>
              <label className="flex items-center gap-2 text-sm sm:col-span-2">
                <input
                  type="checkbox"
                  className="size-4 accent-primary"
                  {...register("is_active")}
                />
                {labels.products.activeLabel}
              </label>
            </div>
          </details>
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center justify-end gap-3">
        <FieldError message={formError} />
        <Button type="button" variant="outline" onClick={() => router.back()}>
          {labels.common.cancel}
        </Button>
        <Button type="submit" disabled={save.isPending}>
          {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
          {labels.products.save}
        </Button>
      </div>
    </form>
  );
}

function Field({
  id,
  label,
  error,
  wide,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={wide ? "space-y-1.5 sm:col-span-2" : "space-y-1.5"}>
      <Label htmlFor={id}>{label}</Label>
      {children}
      <FieldError message={error} />
    </div>
  );
}
