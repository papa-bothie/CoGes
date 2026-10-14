"use client";

import { Loader2 } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { FieldError } from "@/components/field-error";
import { AmountField, NumericPad } from "@/components/kit/amount-field";
import { ChoiceTiles } from "@/components/kit/choice-tile";
import { PaymentMethodChips } from "@/components/kit/payment-method-chips";
import { TODAY, WhenChips, whenDay, type When } from "@/components/kit/when-chips";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { MONEY_KEYS } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { expenseIcon } from "@/lib/expense-icons";
import { labels } from "@/lib/labels";
import { typedAmount } from "@/lib/payment-amount";

type Category = Schemas["ExpenseCategoryRead"];
type Method = Schemas["PaymentMethod"];

/** Icône d'une catégorie de la maquette (20), par son nom ; un reçu pour les autres. */

/**
 * Nouvelle dépense (maquette 20) : « Pour quoi ? » en tuiles, « Combien ? » tapé avec le
 * pavé, « Quand ? », « Payé avec ». Le libellé est le nom de la catégorie : rien à écrire.
 * Le décaissement part **dans la même transaction**, sous la même `Idempotency-Key`
 * (ADR 0053) ; sans `payments:create`, la dépense est enregistrée sans paiement.
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
  const [categoryId, setCategoryId] = useState<string | undefined>(undefined);
  const [amount, setAmount] = useState("");
  const [when, setWhen] = useState<When>(TODAY);
  const [method, setMethod] = useState<Method>("cash");
  const [formError, setFormError] = useState<string | null>(null);
  const t = labels.finance.expenses;

  const reset = () => {
    setCategoryId(undefined);
    setAmount("");
    setWhen(TODAY);
    setMethod("cash");
    setFormError(null);
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
    onError: (error) => setFormError(errorMessage(error)),
  });

  const category = categories.find((item) => item.id === categoryId);
  const ready = Boolean(category) && typedAmount(amount) > 0n;

  const submit = () => {
    if (!category || !ready) return;
    setFormError(null);
    create.mutate({
      category_id: category.id,
      label: category.name,
      amount,
      spent_at: whenDay(when, timeZone),
      payment: canPay ? { method } : null,
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
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t.formTitle}</DialogTitle>
        </DialogHeader>
        <form
          className="space-y-5"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <div className="space-y-2">
            <p className="text-libelle">{t.forWhat}</p>
            {categories.length === 0 ? (
              <p className="text-corps text-muted-foreground">{t.noCategories}</p>
            ) : (
              <ChoiceTiles
                label={t.forWhat}
                value={categoryId}
                onValueChange={setCategoryId}
                rubrique="depenses"
                choices={categories.map((item) => ({
                  value: item.id,
                  label: item.name,
                  icon: expenseIcon(item.name),
                }))}
              />
            )}
          </div>
          <div className="space-y-3">
            <AmountField
              id="expense-amount"
              label={t.howMuch}
              value={amount}
              onChange={setAmount}
              rubrique="depenses"
            />
            <NumericPad value={amount} onChange={setAmount} rubrique="depenses" />
          </div>
          <WhenChips value={when} onChange={setWhen} timeZone={timeZone} />
          {canPay && (
            <PaymentMethodChips
              value={method}
              onChange={setMethod}
              rubrique="depenses"
              label={t.paidWith}
            />
          )}

          <FieldError message={formError} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {labels.common.close}
            </Button>
            <Button type="submit" variant="depenses" disabled={!ready || create.isPending}>
              {create.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t.submit}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
