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
import { parseDecimalInput, toInputDecimal } from "@/lib/decimal";
import { labels } from "@/lib/labels";

type Customer = Schemas["CustomerRead"];

/** Bornes de `CustomerCreate` ; le serveur revalide. */
const schema = z.object({
  name: z.string().trim().min(1, labels.validation.required).max(200),
  code: z.string().trim().max(32),
  phone: z.string().trim().max(40),
  email: z
    .string()
    .trim()
    .refine((value) => !value || z.email().safeParse(value).success, labels.validation.email),
  credit_limit: z
    .string()
    .refine(
      (value) => !value.trim() || parseDecimalInput(value) !== null,
      labels.sales.invalidNumber,
    ),
});
type Values = z.infer<typeof schema>;

/**
 * Création ou modification d'un client. En modification, un champ facultatif vidé est
 * envoyé à `null` : c'est ainsi que l'API l'efface (PATCH partiel).
 */
export function CustomerFormDialog({
  customer,
  open,
  onOpenChange,
  onSaved,
}: {
  customer?: Customer;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved?: (customer: Customer) => void;
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
      name: customer?.name ?? "",
      code: customer?.code ?? "",
      phone: customer?.phone ?? "",
      email: customer?.email ?? "",
      credit_limit: customer?.credit_limit ? toInputDecimal(customer.credit_limit) : "",
    },
  });

  const save = useMutation({
    meta: { toastError: false },
    mutationFn: (values: Values) => {
      const body = {
        name: values.name,
        code: values.code || null,
        phone: values.phone || null,
        email: values.email || null,
        credit_limit: values.credit_limit.trim() ? parseDecimalInput(values.credit_limit) : null,
      };
      return customer
        ? unwrap(
            api.PATCH("/api/v1/customers/{customer_id}", {
              params: { path: { customer_id: customer.id } },
              body,
            }),
          )
        : unwrap(api.POST("/api/v1/customers", { body }));
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.customers.detail(saved.id), saved);
      void queryClient.invalidateQueries({ queryKey: queryKeys.customers.all });
      toast.success(customer ? labels.customers.saved : labels.customers.created);
      onOpenChange(false);
      onSaved?.(saved);
    },
    onError: (error) => {
      if (isApiError(error) && error.code === "customer_code_taken") {
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
    options: { inputMode?: "decimal" | "tel" | "email"; className?: string } = {},
  ) => (
    <div className="space-y-1.5">
      <Label htmlFor={`customer-${name}`}>{label}</Label>
      <Input
        id={`customer-${name}`}
        inputMode={options.inputMode}
        aria-invalid={Boolean(errors[name])}
        className={options.className}
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
            {customer ? labels.customers.editTitle : labels.customers.createTitle}
          </DialogTitle>
          <DialogDescription>{labels.customers.creditLimitHint}</DialogDescription>
        </DialogHeader>
        <form
          noValidate
          className="space-y-4"
          onSubmit={handleSubmit((values) => {
            setFormError(null);
            save.mutate(values);
          })}
        >
          {field("name", labels.customers.name)}
          <div className="grid gap-4 sm:grid-cols-2">
            {field("code", labels.customers.codeLabel)}
            {field("phone", labels.customers.phoneLabel, { inputMode: "tel" })}
          </div>
          {field("email", labels.customers.emailLabel, { inputMode: "email" })}
          {field("credit_limit", labels.customers.creditLimitLabel, {
            inputMode: "decimal",
            className: "text-right numeric",
          })}
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
