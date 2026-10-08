"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { FieldError } from "@/components/field-error";
import { PaymentAmount } from "@/components/kit/payment-amount";
import { PaymentMethodChips } from "@/components/kit/payment-method-chips";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { splitAcrossDebts } from "@/lib/allocation";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { MONEY_KEYS, queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatDate } from "@/lib/format";
import { formatAmount } from "@/lib/format/money";
import { labels } from "@/lib/labels";
import { debtPaymentCheck, debtShortcuts, wholeUnits } from "@/lib/payment-amount";

type Debt = Schemas["DebtDetail"];
type Method = Schemas["PaymentMethod"];

const OPEN = new Set<Debt["status"]>(["open", "partially_paid"]);

function partyFilter(debt: Debt) {
  return debt.party_type === "customer"
    ? { party_type: "customer" as const, customer_id: debt.customer_id ?? undefined }
    : { party_type: "supplier" as const, supplier_id: debt.supplier_id ?? undefined };
}

/**
 * Encaisser une dette ou payer un fournisseur (maquettes 18 et 19). Le montant se tape
 * librement, de 1 F jusqu'au total dû ; il couvre les dettes du tiers les plus anciennes
 * d'abord (`POST /payments` avec `allocations`). Ni référence ni note : elles restent
 * facultatives dans l'API.
 */
export function SettleDialog({ debt, onClose }: { debt: Debt; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { currency, timeZone } = useCompanyLocale();
  const idempotency = useIdempotencyKey();
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<Method>("cash");
  const [formError, setFormError] = useState<string | null>(null);
  const t = labels.finance.debts;
  const kind = debt.party_type;
  const payer = kind === "customer" ? "client" : "fournisseur";

  const params = { ...partyFilter(debt), page_size: 100 };
  const siblings = useQuery({
    queryKey: queryKeys.debts.list(params),
    queryFn: () => unwrap(api.GET("/api/v1/debts", { params: { query: params } })),
  });
  // Ordre du serveur : échéance la plus proche d'abord, sans échéance en dernier.
  const openDebts = (siblings.data?.items ?? []).filter((item) => OPEN.has(item.status));
  const due = openDebts.reduce((sum, item) => sum + wholeUnits(item.balance), 0n);
  const check = debtPaymentCheck(amount, due, payer, currency);

  const settle = useMutation({
    meta: { toastError: false },
    mutationFn: (body: Schemas["PaymentCreate"]) =>
      unwrap(api.POST("/api/v1/payments", { body, headers: idempotency.headers })),
    onSuccess: () => {
      idempotency.renew();
      for (const key of MONEY_KEYS) void queryClient.invalidateQueries({ queryKey: key });
      toast.success(t.settled[kind]);
      onClose();
    },
    onError: (error) => setFormError(errorMessage(error)),
  });

  const submit = () => {
    if (!check.ok) return;
    const shares = splitAcrossDebts(amount, openDebts);
    setFormError(null);
    settle.mutate({
      direction: kind === "customer" ? "inflow" : "outflow",
      method,
      amount,
      allocations: Object.entries(shares).map(([debt_id, share]) => ({
        debt_id,
        amount: share,
      })),
    });
  };

  const party = debt.party_name ?? t.deletedParty;
  const rubrique = kind === "customer" ? "clients" : "argent";

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t.settleTitle[kind]}</DialogTitle>
          <DialogDescription>{party}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-5"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          {siblings.isPending ? (
            <Skeleton className="h-24 w-full" />
          ) : (
            <section className="space-y-2">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-libelle">{t.owes[kind]}</span>
                <span className="text-chiffre numeric">
                  {formatAmount(due.toString(), currency)}
                </span>
              </div>
              <p className="text-petit font-bold text-muted-foreground">{t.purchases[kind]}</p>
              <ul className="divide-y rounded-champ border">
                {openDebts.map((item) => (
                  <li key={item.id} className="flex items-center justify-between gap-3 px-4 py-3">
                    <span className="text-corps numeric">
                      {t.debtLine(
                        formatDate(item.created_at, timeZone),
                        formatAmount(item.principal, currency),
                      )}
                    </span>
                    <span className="text-corps font-bold numeric text-stock-encre">
                      {t.remainingShort(formatAmount(item.balance, currency))}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <PaymentAmount
            id="settle-amount"
            label={labels.payment[payer].amount}
            value={amount}
            onChange={setAmount}
            shortcuts={debtShortcuts(due, currency)}
            check={check}
            rubrique={rubrique}
          />
          <PaymentMethodChips value={method} onChange={setMethod} rubrique={rubrique} />

          <FieldError message={formError} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {labels.common.close}
            </Button>
            <Button
              type="submit"
              variant={rubrique}
              disabled={!check.ok || settle.isPending || siblings.isPending}
            >
              {settle.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t.settleSubmit[kind]}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
