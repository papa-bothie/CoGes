"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { FieldError } from "@/components/field-error";
import { Button } from "@/components/ui/button";
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
import { api, unwrap } from "@/lib/api/client";
import { errorMessage, isApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { labels } from "@/lib/labels";

type Supplier = Schemas["SupplierRead"];

/** Bornes de `SupplierCreate` (délai entier de 0 à 365 jours) ; le serveur revalide. */
const schema = z.object({
  name: z.string().trim().min(1, labels.validation.required).max(200),
  code: z.string().trim().max(32),
  phone: z.string().trim().max(40),
  payment_terms_days: z
    .string()
    .trim()
    .refine(
      (value) => !value || (/^\d{1,3}$/.test(value) && Number(value) <= 365),
      labels.suppliers.termsInvalid,
    ),
});
type Values = z.infer<typeof schema>;

export function SupplierFormDialog({
  supplier,
  open,
  onOpenChange,
  onSaved,
}: {
  supplier?: Supplier;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved?: (supplier: Supplier) => void;
}) {
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    values: {
      name: supplier?.name ?? "",
      code: supplier?.code ?? "",
      phone: supplier?.phone ?? "",
      payment_terms_days:
        supplier?.payment_terms_days === null || supplier?.payment_terms_days === undefined
          ? ""
          : String(supplier.payment_terms_days),
    },
  });

  const save = useMutation({
    meta: { toastError: false },
    mutationFn: (values: Values) => {
      const body = {
        name: values.name,
        code: values.code || null,
        phone: values.phone || null,
        payment_terms_days: values.payment_terms_days ? Number(values.payment_terms_days) : null,
      };
      return supplier
        ? unwrap(
            api.PATCH("/api/v1/suppliers/{supplier_id}", {
              params: { path: { supplier_id: supplier.id } },
              body,
            }),
          )
        : unwrap(api.POST("/api/v1/suppliers", { body }));
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.suppliers.detail(saved.id), saved);
      void queryClient.invalidateQueries({ queryKey: queryKeys.suppliers.all });
      toast.success(supplier ? labels.suppliers.saved : labels.suppliers.created);
      onOpenChange(false);
      onSaved?.(saved);
    },
    onError: (error) => {
      if (isApiError(error) && error.code === "supplier_code_taken") {
        setError("code", { message: error.message });
        return;
      }
      if (isApiError(error) && error.status === 422) {
        for (const name of Object.keys(error.fieldErrors())) {
          if (name in schema.shape) {
            setError(name as keyof Values, { message: labels.validation.invalidValue });
          }
        }
      }
      setFormError(errorMessage(error));
    },
  });

  const field = (
    name: keyof Values,
    label: string,
    options: { inputMode?: "numeric" | "tel" } = {},
  ) => (
    <div className="space-y-1.5">
      <Label htmlFor={`supplier-${name}`}>{label}</Label>
      <Input
        id={`supplier-${name}`}
        inputMode={options.inputMode}
        aria-invalid={Boolean(errors[name])}
        {...register(name)}
      />
      <FieldError message={errors[name]?.message} />
    </div>
  );

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          reset();
          setFormError(null);
        }
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {supplier ? labels.suppliers.editTitle : labels.suppliers.createTitle}
          </DialogTitle>
          <DialogDescription>{labels.suppliers.termsHint}</DialogDescription>
        </DialogHeader>
        <form
          noValidate
          className="space-y-4"
          onSubmit={handleSubmit((values) => {
            setFormError(null);
            save.mutate(values);
          })}
        >
          {field("name", labels.suppliers.name)}
          <div className="grid gap-4 sm:grid-cols-2">
            {field("code", labels.suppliers.codeLabel)}
            {field("phone", labels.suppliers.phoneLabel, { inputMode: "tel" })}
          </div>
          {field("payment_terms_days", labels.suppliers.termsLabel, { inputMode: "numeric" })}
          <FieldError message={formError} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {labels.common.close}
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {labels.common.save}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
