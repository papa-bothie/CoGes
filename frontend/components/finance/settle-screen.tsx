"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { PaymentAmount } from "@/components/kit/payment-amount";
import { PaymentMethodChips } from "@/components/kit/payment-method-chips";
import { RUBRIQUE_CLASSES } from "@/components/kit/rubrique";
import { StatusPill } from "@/components/kit/status-pill";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { splitAcrossDebts } from "@/lib/allocation";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { MONEY_KEYS, queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatAmount, formatDayMonth } from "@/lib/format";
import { labels } from "@/lib/labels";
import { daysUntil, DUE_SOON_DAYS } from "@/lib/money";
import { debtPaymentCheck, debtShortcuts, wholeUnits } from "@/lib/payment-amount";
import { todayIn } from "@/lib/period";
import { initials, shortNames, sinceText } from "@/lib/people";
import { cn } from "@/lib/utils";

type Kind = "customer" | "supplier";
type Person = Schemas["PersonRow"];
type Debt = Schemas["DebtDetail"];
type Method = Schemas["PaymentMethod"];

const t = labels.moneyScreens;
const OPEN = new Set<Debt["status"]>(["open", "partially_paid"]);
const SETUP = {
  customer: {
    copy: t.collect,
    rubrique: "clients",
    payer: "client",
    path: "/finance/collect",
    param: "customer",
    list: "/api/v1/analytics/customers",
  },
  supplier: {
    copy: t.pay,
    rubrique: "argent",
    payer: "fournisseur",
    path: "/finance/pay",
    param: "supplier",
    list: "/api/v1/analytics/suppliers",
  },
} as const;

/** Clients : la plus vieille dette d'abord ; fournisseurs : l'échéance la plus proche. */
function byUrgency(kind: Kind) {
  return (a: Person, b: Person) => {
    const left = kind === "customer" ? (a.owed_since ?? "") : (a.due_date ?? "9999");
    const right = kind === "customer" ? (b.owed_since ?? "") : (b.due_date ?? "9999");
    return left.localeCompare(right) || a.name.localeCompare(b.name, "fr");
  };
}

/** Dettes à régler dans l'ordre de la maquette : les plus anciennes achats d'abord. */
function settleOrder(kind: Kind) {
  return (a: Debt, b: Debt) =>
    kind === "supplier" && (a.due_date ?? "") !== (b.due_date ?? "")
      ? (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999")
      : a.created_at.localeCompare(b.created_at);
}

/**
 * Encaisser une dette (maquette 18 et 18b, violet) ou payer un fournisseur (19, bleu) :
 * à gauche ceux qui doivent (ou à qui l'on doit), à droite la personne choisie, le montant
 * tapé librement de 1 F jusqu'au total, et le moyen. Le versement couvre ses dettes les
 * plus anciennes d'abord (`POST /payments` avec `allocations`, sous clé d'idempotence).
 */
export function SettleScreen({ kind }: { kind: Kind }) {
  const setup = SETUP[kind];
  const { currency, timeZone } = useCompanyLocale();
  const router = useRouter();
  const searchParams = useSearchParams();
  const requested = searchParams.get(setup.param);
  // Ceux qui viennent de tout payer restent dans la liste, « Rien » en vert.
  const [cleared, setCleared] = useState<Record<string, Person>>({});

  const people = useQuery({
    queryKey: queryKeys.people.list(kind, { owing: true, page_size: 100 }),
    queryFn: () =>
      unwrap(
        api.GET(setup.list, {
          params: { query: { owing: true, page_size: 100 } },
        }),
      ),
  });

  if (people.isError) {
    return <ErrorState error={people.error} onRetry={() => void people.refetch()} />;
  }
  const owing = [...(people.data?.items ?? [])].sort(byUrgency(kind));
  const rows = [
    ...owing,
    ...Object.values(cleared).filter((person) => !owing.some((row) => row.id === person.id)),
  ];
  const selected = rows.find((row) => row.id === requested) ?? rows[0];
  const total = people.data?.owed_total ?? "0";
  const today = todayIn(timeZone);
  const tone = RUBRIQUE_CLASSES[setup.rubrique];

  const pick = (id: string) =>
    router.replace(`${setup.path}?${setup.param}=${id}`, { scroll: false });

  return (
    <div className="mx-auto flex max-w-page flex-col gap-5">
      <div>
        <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{setup.copy.title}</h1>
        <p className="text-lg text-muted-foreground">
          {kind === "customer" ? (
            <>
              {t.collect.summary}{" "}
              <strong className={cn("font-extrabold numeric", tone.ink)}>
                {formatAmount(total, currency)}
              </strong>
            </>
          ) : (
            <>
              {t.pay.summary.before}{" "}
              <strong className={cn("font-extrabold numeric", tone.ink)}>
                {formatAmount(total, currency)}
              </strong>{" "}
              {t.pay.summary.after}
            </>
          )}
        </p>
      </div>

      {!people.data ? (
        <Skeleton className="h-[560px] w-full rounded-carte" />
      ) : rows.length === 0 ? (
        <p className="rounded-carte border border-border bg-card p-carte text-lg">
          {setup.copy.empty}
        </p>
      ) : (
        <div className="flex flex-wrap items-start gap-5">
          <ul
            aria-label={setup.copy.list}
            className="flex min-w-0 flex-[2_1_320px] flex-col gap-1 rounded-carte border border-border bg-card p-3"
          >
            {rows.map((person) => {
              const isCleared = !!cleared[person.id] && !owing.some((row) => row.id === person.id);
              const soon =
                kind === "supplier" &&
                person.due_date !== null &&
                daysUntil(person.due_date, today) <= DUE_SOON_DAYS;
              return (
                <li key={person.id}>
                  <button
                    type="button"
                    aria-current={person.id === selected?.id || undefined}
                    onClick={() => pick(person.id)}
                    className={cn(
                      "flex w-full items-center gap-3.5 rounded-[18px] border-2 border-transparent px-3.5 text-left outline-none",
                      "focus-visible:ring-3 focus-visible:ring-ring/50",
                      kind === "customer" ? "min-h-[72px]" : "min-h-[76px]",
                      person.id === selected?.id ? tone.picked : "hover:bg-voile",
                    )}
                  >
                    <span
                      aria-hidden
                      className={cn(
                        "flex size-[46px] shrink-0 items-center justify-center font-bold",
                        kind === "customer" ? "rounded-full" : "rounded-[14px]",
                        tone.solid,
                      )}
                    >
                      {initials(person.name)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[17px] font-bold text-foreground">
                        {person.name}
                      </span>
                      <span
                        className={cn(
                          "block",
                          soon && !isCleared
                            ? "font-semibold text-stock-encre"
                            : "text-muted-foreground",
                          kind === "supplier" && "font-semibold",
                        )}
                      >
                        {isCleared
                          ? setup.copy.cleared
                          : kind === "customer"
                            ? person.owed_since
                              ? sinceText(person.owed_since, timeZone)
                              : null
                            : person.due_date
                              ? soon
                                ? t.payBeforeSoon(
                                    formatDayMonth(person.due_date),
                                    daysUntil(person.due_date, today),
                                  )
                                : t.payBefore(formatDayMonth(person.due_date))
                              : t.pay.noDue}
                      </span>
                    </span>
                    <span
                      className={cn(
                        "text-lg font-extrabold numeric",
                        isCleared ? "text-marque" : tone.ink,
                      )}
                    >
                      {isCleared ? setup.copy.nothing : formatAmount(person.owed, currency)}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          {selected ? (
            <SettlePanel
              key={selected.id}
              kind={kind}
              person={selected}
              onCleared={(person) => setCleared((all) => ({ ...all, [person.id]: person }))}
            />
          ) : null}
        </div>
      )}

      <Link
        href="/finance/debts"
        className="min-h-11 self-start font-semibold text-muted-foreground underline-offset-4 hover:underline pointer-coarse:min-h-12"
      >
        {t.allDebts}
      </Link>
    </div>
  );
}

function SettlePanel({
  kind,
  person,
  onCleared,
}: {
  kind: Kind;
  person: Person;
  onCleared: (person: Person) => void;
}) {
  const setup = SETUP[kind];
  const tone = RUBRIQUE_CLASSES[setup.rubrique];
  const queryClient = useQueryClient();
  const { currency, timeZone } = useCompanyLocale();
  const idempotency = useIdempotencyKey();
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<Method>("cash");
  const [done, setDone] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  // Les dettes réglées par ce versement restent affichées, « Payé ».
  const [touched, setTouched] = useState<string[]>([]);

  const filter = kind === "customer" ? { customer_id: person.id } : { supplier_id: person.id };
  const debts = useQuery({
    queryKey: queryKeys.debts.list({ ...filter, page_size: 100 }),
    queryFn: () =>
      unwrap(api.GET("/api/v1/debts", { params: { query: { ...filter, page_size: 100 } } })),
  });
  const purchases = useQuery({
    queryKey: queryKeys.people.history("customer", person.id, "sales-100"),
    enabled: kind === "customer",
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/analytics/customers/{customer_id}/sales", {
          params: { path: { customer_id: person.id }, query: { page_size: 100 } },
        }),
      ),
  });

  const all = [...(debts.data?.items ?? [])].sort(settleOrder(kind));
  const open = all.filter((debt) => OPEN.has(debt.status));
  const shown = all.filter((debt) => OPEN.has(debt.status) || touched.includes(debt.id));
  const due = open.reduce((sum, debt) => sum + wholeUnits(debt.balance), 0n);
  const check = debtPaymentCheck(amount, due, setup.payer, currency);
  const shortcuts = debtShortcuts(due, currency).slice(0, kind === "customer" ? 3 : 2);
  const names = new Map(
    (purchases.data?.items ?? []).map((sale) => [sale.sale_id, shortNames(sale.item_names)]),
  );

  const settle = useMutation({
    meta: { toastError: false },
    mutationFn: (body: Schemas["PaymentCreate"]) =>
      unwrap(api.POST("/api/v1/payments", { body, headers: idempotency.headers })),
    onSuccess: (_, body) => {
      idempotency.renew();
      const paid = wholeUnits(String(body.amount));
      const rest = due - paid;
      setTouched((ids) => [...ids, ...(body.allocations ?? []).map((a) => a.debt_id)]);
      setDone(
        rest === 0n
          ? setup.copy.doneAll(person.name)
          : setup.copy.donePart(
              formatAmount(paid.toString(), currency),
              formatAmount(rest.toString(), currency),
            ),
      );
      if (rest === 0n) onCleared(person);
      setAmount("");
      for (const key of MONEY_KEYS) void queryClient.invalidateQueries({ queryKey: key });
    },
    onError: (error) => setFormError(errorMessage(error)),
  });

  const submit = () => {
    if (!check.ok || settle.isPending) return;
    const shares = splitAcrossDebts(amount, open);
    setFormError(null);
    setDone(null);
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

  const owes = due > 0n;
  return (
    <section
      aria-label={person.name}
      className="flex min-w-0 flex-[3_1_460px] flex-col gap-5 rounded-carte border border-border bg-card p-carte"
    >
      {done && (
        <div
          role="status"
          className="flex items-center gap-3.5 rounded-champ bg-ventes-teinte px-4 py-3.5 text-lg font-bold text-marque"
        >
          {kind === "customer" && (
            <span
              aria-hidden
              className="flex size-11 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground"
            >
              <CheckCircle2 className="size-6" />
            </span>
          )}
          {done}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-4">
        {kind === "customer" && (
          <span
            aria-hidden
            className={cn(
              "flex size-14 shrink-0 items-center justify-center rounded-full text-xl font-extrabold",
              tone.solid,
            )}
          >
            {initials(person.name)}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-2xl font-bold">{person.name}</h2>
          {kind === "customer" && person.phone && (
            <p className="numeric text-muted-foreground">{person.phone}</p>
          )}
        </div>
        <div className="text-right">
          <p className="font-semibold text-muted-foreground">
            {kind === "customer" ? t.collect.owesStill : t.pay.owe}
          </p>
          <p className={cn("text-[34px] leading-tight font-extrabold numeric", tone.ink)}>
            {debts.data ? formatAmount(due.toString(), currency) : "…"}
          </p>
        </div>
      </div>

      {kind === "customer" && shown.length > 0 && (
        <div>
          <h3 className="border-b border-filet pb-2 text-[17px] font-bold">
            {t.collect.purchases}
          </h3>
          <ul>
            {shown.map((debt) => (
              <li
                key={debt.id}
                className="flex items-center justify-between gap-3 border-b border-filet py-3"
              >
                <span className="min-w-0">
                  <span className="block font-bold">
                    {(debt.sale_id && names.get(debt.sale_id)) || t.collect.manual}
                  </span>
                  <span className="block numeric text-muted-foreground">
                    {t.collect.purchaseLine(
                      formatDayMonth(debt.created_at, timeZone),
                      formatAmount(debt.principal, currency),
                    )}
                  </span>
                </span>
                {OPEN.has(debt.status) ? (
                  <StatusPill
                    status="remaining"
                    amount={formatAmount(debt.balance, currency)}
                    className="min-w-[120px]"
                  />
                ) : (
                  <StatusPill status="paid" className="min-w-[120px]" />
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {!debts.data ? (
        <Skeleton className="h-96 w-full" />
      ) : owes ? (
        <form
          noValidate
          className="flex flex-col gap-5"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <PaymentAmount
            label={labels.payment[setup.payer].amount}
            value={amount}
            onChange={(value) => {
              setAmount(value);
              setFormError(null);
            }}
            shortcuts={shortcuts}
            check={check}
            rubrique={setup.rubrique}
            placeholder={labels.payment.typeAmount}
            shortcutsClassName={kind === "customer" ? "sm:grid-cols-3" : undefined}
            padClassName="max-w-[420px]"
          />
          <PaymentMethodChips
            value={method}
            onChange={setMethod}
            rubrique={setup.rubrique}
            tone="teinte"
            stretch
          />
          <FieldError message={formError} />
          <button
            type="submit"
            disabled={!check.ok || settle.isPending}
            className={cn(
              "flex min-h-[68px] items-center justify-center gap-2.5 rounded-bouton text-[21px] font-bold",
              "outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-45",
              tone.solid,
            )}
          >
            {settle.isPending ? (
              <Loader2 className="size-6 animate-spin" aria-hidden />
            ) : (
              kind === "customer" && <Check className="size-6" aria-hidden />
            )}
            {setup.copy.submit(formatAmount(check.ok ? amount : "0", currency))}
          </button>
        </form>
      ) : null}
    </section>
  );
}
