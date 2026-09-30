"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

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
import { errorMessage } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { MONEY_KEYS } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal, parseDecimalInput, toInputDecimal } from "@/lib/decimal";
import { zonedDateTimeIso } from "@/lib/format/zoned";
import { labels } from "@/lib/labels";

type Direction = Schemas["CashDirection"];
type Method = Schemas["PaymentMethod"];

export const PAYMENT_METHODS: readonly Method[] = [
  "cash",
  "mobile_money",
  "bank_transfer",
  "card",
  "cheque",
];

/** Règlement d'une dépense : le décaissement lui est rattaché (`expense_id`). */
export type ExpenseTarget = { id: string; label: string; suggested: string };

/**
 * Encaissement ou décaissement saisi à la main (`POST /payments`), ou règlement d'une
 * dépense. `Idempotency-Key` gardée jusqu'au succès (ADR 0027, 0052).
 */
export function PaymentDialog({
  open,
  onOpenChange,
  expense,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  expense?: ExpenseTarget | null;
}) {
  const queryClient = useQueryClient();
  const { timeZone } = useCompanyLocale();
  const idempotency = useIdempotencyKey();
  const [direction, setDirection] = useState<Direction>("inflow");
  const [method, setMethod] = useState<Method>("cash");
  const [amount, setAmount] = useState(() => (expense ? toInputDecimal(expense.suggested) : ""));
  const [paidAt, setPaidAt] = useState("");
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<{ amount?: string; form?: string }>({});
  const t = labels.finance.payments;

  const reset = () => {
    setDirection("inflow");
    setMethod("cash");
    setAmount("");
    setPaidAt("");
    setReference("");
    setNote("");
    setErrors({});
  };

  const record = useMutation({
    meta: { toastError: false },
    mutationFn: (body: Schemas["PaymentCreate"]) =>
      unwrap(api.POST("/api/v1/payments", { body, headers: idempotency.headers })),
    onSuccess: () => {
      idempotency.renew();
      for (const key of MONEY_KEYS) void queryClient.invalidateQueries({ queryKey: key });
      toast.success(expense ? labels.finance.expenses.paid : t.recorded);
      reset();
      onOpenChange(false);
    },
    onError: (error) => setErrors({ form: errorMessage(error) }),
  });

  const submit = () => {
    const parsed = parseDecimalInput(amount);
    if (parsed === null || compareDecimal(parsed, "0") !== 1) {
      setErrors({ amount: labels.validation.positiveAmount });
      return;
    }
    setErrors({});
    record.mutate({
      direction: expense ? "outflow" : direction,
      method,
      amount: parsed,
      paid_at: paidAt ? zonedDateTimeIso(paidAt, timeZone) : null,
      reference: reference.trim() || null,
      note: note.trim() || null,
      expense_id: expense?.id ?? null,
      allocations: [],
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
          <DialogTitle>
            {expense ? labels.finance.expenses.payTitle(expense.label) : t.formTitle}
          </DialogTitle>
          {!expense && <DialogDescription>{t.formDescription}</DialogDescription>}
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
            {!expense && (
              <div className="space-y-1.5">
                <Label htmlFor="payment-direction">{t.columns.direction}</Label>
                <Select value={direction} onValueChange={(v) => setDirection(v as Direction)}>
                  <SelectTrigger id="payment-direction" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="inflow">{t.direction.inflow}</SelectItem>
                    <SelectItem value="outflow">{t.direction.outflow}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="payment-method">{t.method}</Label>
              <Select value={method} onValueChange={(v) => setMethod(v as Method)}>
                <SelectTrigger id="payment-method" className="w-full">
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
            <div className="space-y-1.5">
              <Label htmlFor="payment-amount">{t.amount}</Label>
              <Input
                id="payment-amount"
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
            <Label htmlFor="payment-date">{t.paidAt}</Label>
            <Input
              id="payment-date"
              type="datetime-local"
              value={paidAt}
              onChange={(event) => setPaidAt(event.target.value)}
              className="h-9"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="payment-reference">{t.reference}</Label>
            <Input
              id="payment-reference"
              value={reference}
              maxLength={100}
              onChange={(event) => setReference(event.target.value)}
              className="h-9"
            />
          </div>
          {!expense && (
            <div className="space-y-1.5">
              <Label htmlFor="payment-note">{t.note}</Label>
              <Textarea
                id="payment-note"
                value={note}
                maxLength={500}
                onChange={(event) => setNote(event.target.value)}
              />
            </div>
          )}
          <FieldError message={errors.form} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {labels.common.close}
            </Button>
            <Button type="submit" disabled={record.isPending}>
              {record.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {expense ? labels.finance.expenses.paySubmit : t.submit}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
