"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { FieldError } from "@/components/field-error";
import { SearchCombobox } from "@/components/search-combobox";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { MONEY_KEYS } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal, parseDecimalInput } from "@/lib/decimal";
import { labels } from "@/lib/labels";

type Supplier = Schemas["SupplierRead"];

export async function searchSuppliers(text: string): Promise<Supplier[]> {
  const page = await unwrap(
    api.GET("/api/v1/suppliers", {
      params: { query: { search: text || undefined, page_size: 8 } },
    }),
  );
  return page.items;
}

/** Dette fournisseur saisie à la main (ADR 0029) : un engagement à régler plus tard. */
export function SupplierDebtDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const idempotency = useIdempotencyKey();
  const [supplier, setSupplier] = useState<Supplier | null>(null);
  const [principal, setPrincipal] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [errors, setErrors] = useState<{ supplier?: string; principal?: string; form?: string }>(
    {},
  );
  const t = labels.finance.debts;

  const reset = () => {
    setSupplier(null);
    setPrincipal("");
    setDueDate("");
    setErrors({});
  };

  const create = useMutation({
    meta: { toastError: false },
    mutationFn: (body: Schemas["DebtCreate"]) =>
      unwrap(api.POST("/api/v1/debts", { body, headers: idempotency.headers })),
    onSuccess: () => {
      idempotency.renew();
      for (const key of MONEY_KEYS) void queryClient.invalidateQueries({ queryKey: key });
      toast.success(t.created);
      reset();
      onOpenChange(false);
    },
    onError: (error) => setErrors({ form: errorMessage(error) }),
  });

  const submit = () => {
    const next: typeof errors = {};
    if (!supplier) next.supplier = labels.validation.required;
    const parsed = parseDecimalInput(principal);
    if (parsed === null || compareDecimal(parsed, "0") !== 1) {
      next.principal = labels.validation.positiveAmount;
    }
    setErrors(next);
    if (Object.keys(next).length > 0 || !supplier || parsed === null) return;
    create.mutate({
      party_type: "supplier",
      supplier_id: supplier.id,
      principal: parsed,
      due_date: dueDate || null,
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
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t.createTitle}</DialogTitle>
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
            <Label>{t.supplier}</Label>
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
                label={t.supplierSearch}
                queryKey={["suppliers", "search"]}
                search={searchSuppliers}
                itemKey={(item) => item.id}
                onSelect={setSupplier}
                renderItem={(item) => item.name}
              />
            )}
            <FieldError message={errors.supplier} />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="debt-principal">{t.principal}</Label>
              <Input
                id="debt-principal"
                inputMode="decimal"
                value={principal}
                aria-invalid={Boolean(errors.principal)}
                onChange={(event) => setPrincipal(event.target.value)}
                className="h-9 text-right numeric"
              />
              <FieldError message={errors.principal} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="debt-due">{t.dueDate}</Label>
              <Input
                id="debt-due"
                type="date"
                value={dueDate}
                onChange={(event) => setDueDate(event.target.value)}
                className="h-9"
              />
            </div>
          </div>
          <FieldError message={errors.form} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {labels.common.close}
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t.createSubmit}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
