"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { FieldError } from "@/components/field-error";
import { ChoiceGroup } from "@/components/kit/choice-group";
import { PaymentAmount } from "@/components/kit/payment-amount";
import { PaymentMethodChips } from "@/components/kit/payment-method-chips";
import { TODAY, WhenChips, whenDay, type When } from "@/components/kit/when-chips";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useCompanyLocale } from "@/hooks/use-me";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { MONEY_KEYS } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatAmount } from "@/lib/format/money";
import { zonedDateTimeIso } from "@/lib/format/zoned";
import { labels } from "@/lib/labels";
import {
  debtPaymentCheck,
  debtShortcuts,
  typedAmount,
  wholeUnits,
  type Check,
} from "@/lib/payment-amount";

type Direction = Schemas["CashDirection"];
type Method = Schemas["PaymentMethod"];

/** Règlement d'une dépense : le décaissement lui est rattaché (`expense_id`). */
export type ExpenseTarget = { id: string; label: string; suggested: string };

/**
 * Encaissement ou décaissement saisi à la main (`POST /payments`), ou règlement d'une
 * dépense. Montant tapé librement avec le pavé, moyen en puces, « Quand ? » ; ni référence
 * ni note (lot 1), elles restent facultatives dans l'API. `Idempotency-Key` gardée
 * jusqu'au succès (ADR 0027, 0052).
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
  const { currency, timeZone } = useCompanyLocale();
  const idempotency = useIdempotencyKey();
  const [direction, setDirection] = useState<Direction>("inflow");
  const [method, setMethod] = useState<Method>("cash");
  const [amount, setAmount] = useState(() =>
    expense ? wholeUnits(expense.suggested).toString() : "",
  );
  const [when, setWhen] = useState<When>(TODAY);
  const [formError, setFormError] = useState<string | null>(null);
  const t = labels.finance.payments;

  const reset = () => {
    setDirection("inflow");
    setMethod("cash");
    setAmount("");
    setWhen(TODAY);
    setFormError(null);
  };

  const sense: Direction = expense ? "outflow" : direction;
  // Une dépense se règle jusqu'à ce qu'il en reste ; un paiement libre, de 1 F à l'infini.
  const due = expense ? wholeUnits(expense.suggested) : null;
  const check: Check =
    due !== null
      ? debtPaymentCheck(amount, due, "fournisseur", currency)
      : typedAmount(amount) > 0n
        ? {
            ok: true,
            tone: "bon",
            message: labels.payment.amountReady(t.direction[sense], formatAmount(amount, currency)),
          }
        : { ok: false, tone: "attente", message: labels.payment.fournisseur.empty };

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
    onError: (error) => setFormError(errorMessage(error)),
  });

  const submit = () => {
    if (!check.ok) return;
    setFormError(null);
    record.mutate({
      direction: sense,
      method,
      amount,
      // Aujourd'hui : l'heure du serveur. Un autre jour : midi, dans le fuseau de l'entreprise.
      paid_at:
        when.kind === "today"
          ? null
          : zonedDateTimeIso(`${whenDay(when, timeZone)}T12:00`, timeZone),
      expense_id: expense?.id ?? null,
      allocations: [],
    });
  };

  const rubrique = sense === "inflow" ? "argent" : "depenses";

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {expense ? labels.finance.expenses.payTitle(expense.label) : t.formTitle}
          </DialogTitle>
          {!expense && <DialogDescription>{t.formDescription}</DialogDescription>}
        </DialogHeader>
        <form
          className="space-y-5"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          {!expense && (
            <ChoiceGroup
              label={t.directionLabel}
              value={direction}
              onValueChange={setDirection}
              rubrique="argent"
              choices={[
                { value: "inflow", label: t.direction.inflow },
                { value: "outflow", label: t.direction.outflow },
              ]}
            />
          )}
          <PaymentAmount
            id="payment-amount"
            label={t.amount}
            value={amount}
            onChange={setAmount}
            shortcuts={due !== null ? debtShortcuts(due, currency) : []}
            check={check}
            rubrique={rubrique}
          />
          <PaymentMethodChips value={method} onChange={setMethod} rubrique={rubrique} />
          <WhenChips value={when} onChange={setWhen} timeZone={timeZone} rubrique={rubrique} />

          <FieldError message={formError} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {labels.common.close}
            </Button>
            <Button type="submit" variant={rubrique} disabled={!check.ok || record.isPending}>
              {record.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {expense ? labels.finance.expenses.paySubmit : t.submit}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
