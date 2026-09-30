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
import { Card, CardContent, CardDescription } from "@/components/ui/card";
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

const UNITS: readonly Unit[] = ["piece", "kg", "litre", "carton", "metre", "paquet"];
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
  unit_price: z.string(),
  cost_price: optionalDecimal(labels.sales.invalidNumber),
});
type Values = z.infer<typeof schema>;

/** Erreurs métier renvoyées sur un champ précis. */
const FIELD_CODES: Record<string, keyof Values> = {
  product_sku_taken: "sku",
  product_barcode_taken: "barcode",
};

/**
 * Création et modification d'un produit. Le prix n'est saisi qu'à la création : ensuite,
 * il se change depuis la fiche, chaque changement étant historisé (ADR 0011).
 */
export function ProductForm({ product }: { product?: Product }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const categories = useCategories();
  const tree = useMemo(() => flattenTree(categories.data ?? []), [categories.data]);
  const [formError, setFormError] = useState<string | null>(null);
  const creating = !product;

  const {
    register,
    control,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(
      creating
        ? schema.refine((values) => parseDecimalInput(values.unit_price) !== null, {
            path: ["unit_price"],
            message: labels.validation.required,
          })
        : schema,
    ),
    defaultValues: {
      name: product?.name ?? "",
      sku: product?.sku ?? "",
      barcode: product?.barcode ?? "",
      category_id: product?.category_id ?? NONE,
      unit: product?.unit ?? "piece",
      is_stock_tracked: product?.is_stock_tracked ?? true,
      is_active: product?.is_active ?? true,
      tax_percent: product ? rateToPercent(product.default_tax_rate) : "18",
      reorder_point: product?.reorder_point ? toInputDecimal(product.reorder_point) : "",
      unit_price: "",
      cost_price: "",
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
      if (!product) {
        return unwrap(
          api.POST("/api/v1/products", {
            body: {
              ...common,
              unit_price: parseDecimalInput(values.unit_price) ?? "0",
              cost_price: values.cost_price.trim() ? parseDecimalInput(values.cost_price) : null,
            },
          }),
        );
      }
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
      toast.success(creating ? labels.products.created : labels.products.saved);
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
          <Field id="sku" label={labels.products.sku} error={errors.sku?.message}>
            <Input id="sku" aria-invalid={Boolean(errors.sku)} {...register("sku")} />
          </Field>
          <Field id="barcode" label={labels.products.barcode} error={errors.barcode?.message}>
            <Input id="barcode" aria-invalid={Boolean(errors.barcode)} {...register("barcode")} />
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
          <Field id="tax" label={labels.products.taxPercent} error={errors.tax_percent?.message}>
            <Input
              id="tax"
              inputMode="decimal"
              aria-invalid={Boolean(errors.tax_percent)}
              className="text-right numeric"
              {...register("tax_percent")}
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
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input
              type="checkbox"
              className="size-4 accent-primary"
              {...register("is_stock_tracked")}
            />
            {labels.products.trackedLabel}
          </label>
          {!creating && (
            <label className="flex items-center gap-2 text-sm sm:col-span-2">
              <input type="checkbox" className="size-4 accent-primary" {...register("is_active")} />
              {labels.products.activeLabel}
            </label>
          )}
        </CardContent>
      </Card>

      {creating && (
        <Card>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <CardDescription className="sm:col-span-2">
              {labels.products.priceOnCreate}
            </CardDescription>
            <Field id="price" label={labels.products.unitPrice} error={errors.unit_price?.message}>
              <Input
                id="price"
                inputMode="decimal"
                aria-invalid={Boolean(errors.unit_price)}
                className="text-right numeric"
                {...register("unit_price")}
              />
            </Field>
            <Field
              id="cost"
              label={labels.products.costPriceLabel}
              error={errors.cost_price?.message}
            >
              <Input
                id="cost"
                inputMode="decimal"
                aria-invalid={Boolean(errors.cost_price)}
                className="text-right numeric"
                {...register("cost_price")}
              />
            </Field>
          </CardContent>
        </Card>
      )}

      <div className="flex flex-wrap items-center justify-end gap-3">
        <FieldError message={formError} />
        <Button type="button" variant="outline" onClick={() => router.back()}>
          {labels.common.cancel}
        </Button>
        <Button type="submit" disabled={save.isPending}>
          {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
          {creating ? labels.products.create : labels.products.save}
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
