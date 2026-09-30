"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Wand2 } from "lucide-react";
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
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { splitAcrossDebts } from "@/lib/allocation";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage, isApiError } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { MONEY_KEYS, queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal, parseDecimalInput, toInputDecimal } from "@/lib/decimal";
import { formatDate, formatMoney } from "@/lib/format";
import { labels } from "@/lib/labels";

import { PAYMENT_METHODS } from "./payment-dialog";

type Debt = Schemas["DebtDetail"];
type Method = Schemas["PaymentMethod"];

const OPEN = new Set<Debt["status"]>(["open", "partially_paid"]);

function partyFilter(debt: Debt) {
  return debt.party_type === "customer"
    ? { party_type: "customer" as const, customer_id: debt.customer_id ?? undefined }
    : { party_type: "supplier" as const, supplier_id: debt.supplier_id ?? undefined };
}

/**
 * Un versement réparti sur les dettes ouvertes d'un même tiers (`POST /payments` avec
 * `allocations`, Diagramme 5). La répartition proposée n'est qu'un préremplissage : le
 * serveur refuse toute affectation au-delà d'un solde ou du versement.
 */
export function SettleDialog({ debt, onClose }: { debt: Debt; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { currency, timeZone } = useCompanyLocale();
  const idempotency = useIdempotencyKey();
  const [amount, setAmount] = useState(() => toInputDecimal(debt.balance));
  const [method, setMethod] = useState<Method>("cash");
  const [reference, setReference] = useState("");
  const [shares, setShares] = useState<Record<string, string>>(() => ({
    [debt.id]: toInputDecimal(debt.balance),
  }));
  const [errors, setErrors] = useState<{
    amount?: string;
    form?: string;
    debts?: Record<string, string>;
  }>({});
  const t = labels.finance.debts;

  const params = { ...partyFilter(debt), page_size: 100 };
  const siblings = useQuery({
    queryKey: queryKeys.debts.list(params),
    queryFn: () => unwrap(api.GET("/api/v1/debts", { params: { query: params } })),
  });
  // Ordre du serveur : échéance la plus proche d'abord, sans échéance en dernier.
  const openDebts = (siblings.data?.items ?? []).filter((item) => OPEN.has(item.status));

  const settle = useMutation({
    meta: { toastError: false },
    mutationFn: (body: Schemas["PaymentCreate"]) =>
      unwrap(api.POST("/api/v1/payments", { body, headers: idempotency.headers })),
    onSuccess: () => {
      idempotency.renew();
      for (const key of MONEY_KEYS) void queryClient.invalidateQueries({ queryKey: key });
      toast.success(t.settled);
      onClose();
    },
    onError: (error) => {
      const debtId = isApiError(error) ? error.details.debt_id : undefined;
      if (typeof debtId === "string") setErrors({ debts: { [debtId]: errorMessage(error) } });
      else setErrors({ form: errorMessage(error) });
    },
  });

  const split = () => {
    const parsed = parseDecimalInput(amount);
    if (parsed === null) {
      setErrors({ amount: labels.validation.positiveAmount });
      return;
    }
    const proposal = splitAcrossDebts(parsed, openDebts);
    setShares(
      Object.fromEntries(Object.entries(proposal).map(([id, v]) => [id, toInputDecimal(v)])),
    );
    setErrors({});
  };

  const submit = () => {
    const parsed = parseDecimalInput(amount);
    if (parsed === null || compareDecimal(parsed, "0") !== 1) {
      setErrors({ amount: labels.validation.positiveAmount });
      return;
    }
    const allocations: Schemas["AllocationInput"][] = [];
    const debtErrors: Record<string, string> = {};
    for (const item of openDebts) {
      const raw = shares[item.id]?.trim();
      if (!raw) continue;
      const share = parseDecimalInput(raw);
      if (share === null || compareDecimal(share, "0") === -1) {
        debtErrors[item.id] = labels.validation.positiveAmount;
      } else if (compareDecimal(share, "0") === 1) {
        allocations.push({ debt_id: item.id, amount: share });
      }
    }
    if (Object.keys(debtErrors).length > 0) {
      setErrors({ debts: debtErrors });
      return;
    }
    if (allocations.length === 0) {
      setErrors({ form: t.nothingAllocated });
      return;
    }
    setErrors({});
    settle.mutate({
      direction: debt.party_type === "customer" ? "inflow" : "outflow",
      method,
      amount: parsed,
      reference: reference.trim() || null,
      allocations,
    });
  };

  const party = debt.party_name ?? t.deletedParty;

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t.settleTitle(party)}</DialogTitle>
          <DialogDescription>{t.settleDescription}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <div className="grid gap-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
            <div className="space-y-1.5">
              <Label htmlFor="settle-amount">{t.settleAmount}</Label>
              <Input
                id="settle-amount"
                inputMode="decimal"
                value={amount}
                aria-invalid={Boolean(errors.amount)}
                onChange={(event) => setAmount(event.target.value)}
                className="h-9 text-right numeric"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="settle-method">{labels.finance.payments.method}</Label>
              <Select value={method} onValueChange={(v) => setMethod(v as Method)}>
                <SelectTrigger id="settle-method" className="w-full">
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
            <Button type="button" variant="outline" onClick={split}>
              <Wand2 aria-hidden />
              {t.split}
            </Button>
          </div>
          <FieldError message={errors.amount} />

          <fieldset className="space-y-2">
            <legend className="sr-only">{t.party[debt.party_type]}</legend>
            {siblings.isPending ? (
              <Skeleton className="h-24 w-full" />
            ) : (
              <ul className="divide-y rounded-lg border">
                {openDebts.map((item) => {
                  const due = item.due_date ? formatDate(item.due_date, timeZone) : t.noDue;
                  return (
                    <li
                      key={item.id}
                      className="grid grid-cols-[1fr_9rem] items-center gap-3 px-3 py-2"
                    >
                      <div className="min-w-0 text-sm">
                        <p className="numeric">
                          {formatDate(item.created_at, timeZone)} ·{" "}
                          {labels.finance.debts.columns.due} {due}
                        </p>
                        <p className="text-muted-foreground">
                          {t.balanceShort(formatMoney(item.balance, currency))}
                        </p>
                        <FieldError message={errors.debts?.[item.id]} />
                      </div>
                      <Input
                        aria-label={t.allocationLabel(due)}
                        inputMode="decimal"
                        placeholder="0"
                        value={shares[item.id] ?? ""}
                        onChange={(event) =>
                          setShares((current) => ({ ...current, [item.id]: event.target.value }))
                        }
                        className="h-9 text-right numeric"
                      />
                    </li>
                  );
                })}
              </ul>
            )}
          </fieldset>

          <div className="space-y-1.5">
            <Label htmlFor="settle-reference">{labels.finance.payments.reference}</Label>
            <Input
              id="settle-reference"
              value={reference}
              maxLength={100}
              onChange={(event) => setReference(event.target.value)}
              className="h-9"
            />
          </div>

          <FieldError message={errors.form} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {labels.common.close}
            </Button>
            <Button type="submit" disabled={settle.isPending}>
              {settle.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t.settleSubmit}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
