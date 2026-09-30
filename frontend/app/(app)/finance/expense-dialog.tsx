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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { MONEY_KEYS } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal, parseDecimalInput } from "@/lib/decimal";
import { labels } from "@/lib/labels";
import { todayIn } from "@/lib/period";

import { PAYMENT_METHODS } from "./payment-dialog";
import { searchSuppliers } from "./supplier-debt-dialog";

type Category = Schemas["ExpenseCategoryRead"];
type Supplier = Schemas["SupplierRead"];
type Method = Schemas["PaymentMethod"];
type Errors = Partial<Record<"category" | "label" | "amount" | "spentAt" | "form", string>>;

/**
 * Constate une dépense ; « payée maintenant » ajoute son décaissement **dans la même
 * transaction** et sous la même `Idempotency-Key` (ADR 0053). Sans `payments:create`,
 * la case n'est pas proposée.
 */
export function ExpenseDialog({
  open,
  onOpenChange,
  categories,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  categories: readonly Category[];
}) {
  const queryClient = useQueryClient();
  const { timeZone } = useCompanyLocale();
  const canPay = usePermission("payments:create");
  const idempotency = useIdempotencyKey();
  const [categoryId, setCategoryId] = useState("");
  const [label, setLabel] = useState("");
  const [amount, setAmount] = useState("");
  const [spentAt, setSpentAt] = useState(() => todayIn(timeZone));
  const [supplier, setSupplier] = useState<Supplier | null>(null);
  const [paidNow, setPaidNow] = useState(true);
  const [method, setMethod] = useState<Method>("cash");
  const [errors, setErrors] = useState<Errors>({});
  const t = labels.finance.expenses;

  const reset = () => {
    setCategoryId("");
    setLabel("");
    setAmount("");
    setSpentAt(todayIn(timeZone));
    setSupplier(null);
    setPaidNow(true);
    setMethod("cash");
    setErrors({});
  };

  const create = useMutation({
    meta: { toastError: false },
    mutationFn: (body: Schemas["ExpenseCreate"]) =>
      unwrap(api.POST("/api/v1/expenses", { body, headers: idempotency.headers })),
    onSuccess: (_data, body) => {
      idempotency.renew();
      for (const key of MONEY_KEYS) void queryClient.invalidateQueries({ queryKey: key });
      toast.success(body.payment ? t.createdPaid : t.created);
      reset();
      onOpenChange(false);
    },
    onError: (error) => setErrors({ form: errorMessage(error) }),
  });

  const submit = () => {
    const next: Errors = {};
    if (!categoryId) next.category = labels.validation.required;
    if (!label.trim()) next.label = labels.validation.required;
    const parsed = parseDecimalInput(amount);
    if (parsed === null || compareDecimal(parsed, "0") !== 1) {
      next.amount = labels.validation.positiveAmount;
    }
    if (!spentAt) next.spentAt = labels.validation.required;
    setErrors(next);
    if (Object.keys(next).length > 0 || parsed === null) return;
    create.mutate({
      category_id: categoryId,
      label: label.trim(),
      amount: parsed,
      spent_at: spentAt,
      supplier_id: supplier?.id ?? null,
      payment: canPay && paidNow ? { method } : null,
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
          <DialogTitle>{t.formTitle}</DialogTitle>
        </DialogHeader>
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="expense-category">{t.category}</Label>
              <Select value={categoryId} onValueChange={setCategoryId}>
                <SelectTrigger
                  id="expense-category"
                  className="w-full"
                  aria-invalid={Boolean(errors.category)}
                >
                  <SelectValue placeholder={t.category} />
                </SelectTrigger>
                <SelectContent>
                  {categories.map((category) => (
                    <SelectItem key={category.id} value={category.id}>
                      {category.name} · {t.kind[category.kind]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FieldError message={errors.category} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="expense-date">{t.spentAt}</Label>
              <Input
                id="expense-date"
                type="date"
                value={spentAt}
                max={todayIn(timeZone)}
                onChange={(event) => setSpentAt(event.target.value)}
                className="h-9"
              />
              <FieldError message={errors.spentAt} />
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-[1fr_10rem]">
            <div className="space-y-1.5">
              <Label htmlFor="expense-label">{t.label}</Label>
              <Input
                id="expense-label"
                value={label}
                maxLength={200}
                aria-invalid={Boolean(errors.label)}
                onChange={(event) => setLabel(event.target.value)}
                className="h-9"
              />
              <FieldError message={errors.label} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="expense-amount">{t.amount}</Label>
              <Input
                id="expense-amount"
                inputMode="decimal"
                value={amount}
                aria-invalid={Boolean(errors.amount)}
                onChange={(event) => setAmount(event.target.value)}
                className="h-9 text-right numeric"
              />
              <FieldError message={errors.amount} />
            </div>
          </div>
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
                label={labels.finance.debts.supplierSearch}
                queryKey={["suppliers", "search"]}
                search={searchSuppliers}
                itemKey={(item) => item.id}
                onSelect={setSupplier}
                renderItem={(item) => item.name}
              />
            )}
          </div>
          {canPay && (
            <div className="space-y-3 rounded-lg border p-3">
              <label className="flex items-center gap-2 text-sm font-medium">
                <input
                  type="checkbox"
                  className="size-4 accent-primary"
                  checked={paidNow}
                  onChange={(event) => setPaidNow(event.target.checked)}
                />
                {t.paidNow}
              </label>
              {paidNow && (
                <div className="space-y-1.5">
                  <Label htmlFor="expense-method">{t.method}</Label>
                  <Select value={method} onValueChange={(v) => setMethod(v as Method)}>
                    <SelectTrigger id="expense-method" className="w-full sm:w-60">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PAYMENT_METHODS.map((value) => (
                        <SelectItem key={value} value={value}>
                          {labels.paymentMethods[value]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
            </div>
          )}
          <FieldError message={errors.form} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {labels.common.close}
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t.submit}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
