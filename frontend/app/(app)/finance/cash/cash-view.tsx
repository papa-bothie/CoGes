"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDownLeft, ArrowUpRight, Loader2, Undo2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { BackLink, keepFrom } from "@/components/back-link";
import { ErrorState } from "@/components/error-state";
import { Chip } from "@/components/kit/chip";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { MONEY_KEYS, queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatAmount } from "@/lib/format";
import { labels } from "@/lib/labels";
import { cashLineDetail, cashLineText, isNegative, netAmount, signedAmount } from "@/lib/money";
import { addDays, todayIn } from "@/lib/period";
import { cn } from "@/lib/utils";

type Line = Schemas["CashJournalLine"];
const t = labels.moneyScreens.cash;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
/** Lignes montrées d'un coup : une journée chargée en compte des centaines. */
const STEP = 50;

/**
 * Entrées et sorties d'un jour, maquette v2 (écrans 21 et 21b) : les totaux, le net par
 * moyen, puis chaque ligne en mots. « Annuler » demande la raison en boutons puis ajoute
 * une ligne inverse (contre-écriture, ADR 0038) : rien n'est effacé.
 */
export function CashView() {
  const { currency, timeZone } = useCompanyLocale();
  const table = useTableParams();
  const today = todayIn(timeZone);
  const yesterday = addDays(today, -1);
  const requested = table.get("day");
  const day = requested && DATE.test(requested) && requested <= today ? requested : today;
  const [choosing, setChoosing] = useState(day !== today && day !== yesterday);

  const cash = useQuery({
    queryKey: queryKeys.analytics.cash(day),
    queryFn: () => unwrap(api.GET("/api/v1/analytics/cash", { params: { query: { day } } })),
  });

  const from = table.get("from");
  const go = (next: string) =>
    table.replaceAll(keepFrom(next === today ? {} : { day: next }, from));

  return (
    <div className="mx-auto flex max-w-page flex-col gap-5">
      <BackLink fallback={{ href: "/finance", label: labels.moneyScreens.title }} />
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{t.title}</h1>
        <div role="group" aria-label={t.day} className="flex flex-wrap gap-2">
          <Chip
            rubrique="argent"
            tone="plein"
            selected={!choosing && day === today}
            onClick={() => {
              setChoosing(false);
              go(today);
            }}
          >
            {t.today}
          </Chip>
          <Chip
            rubrique="argent"
            tone="plein"
            selected={!choosing && day === yesterday}
            onClick={() => {
              setChoosing(false);
              go(yesterday);
            }}
          >
            {t.yesterday}
          </Chip>
          <Chip
            rubrique="argent"
            tone="plein"
            selected={choosing}
            onClick={() => setChoosing(true)}
          >
            {t.chooseDay}
          </Chip>
        </div>
      </div>
      {choosing && (
        <label className="flex flex-col items-end gap-1 self-end font-semibold">
          {t.day}
          <input
            type="date"
            value={day}
            max={today}
            onChange={(event) => DATE.test(event.target.value) && go(event.target.value)}
            className="min-h-cible rounded-champ border-2 border-input bg-card px-3 text-foreground outline-none focus-visible:border-argent"
          />
        </label>
      )}

      {cash.isError ? (
        <ErrorState error={cash.error} onRetry={() => void cash.refetch()} />
      ) : !cash.data ? (
        <Skeleton className="h-[560px] w-full rounded-carte" />
      ) : (
        <CashBody data={cash.data} currency={currency} timeZone={timeZone} />
      )}

      <p className="text-muted-foreground">{t.footer}</p>
    </div>
  );
}

function CashBody({
  data,
  currency,
  timeZone,
}: {
  data: Schemas["CashJournal"];
  currency: string;
  timeZone: string;
}) {
  const canCancel = usePermission("payments:cancel");
  const [shown, setShown] = useState(STEP);
  const rest = data.lines.length - shown;
  return (
    <>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-3">
        <Total label={t.in} value={formatAmount(data.cash_in, currency)} tone="in" />
        <Total label={t.out} value={formatAmount(data.cash_out, currency)} tone="out" />
        <Total label={t.difference} value={signedAmount(data.net_cash, currency)} tone="net" />
      </div>

      {data.by_method.length > 0 && (
        <section className="rounded-carte border border-border bg-card p-5">
          <h2 className="mb-3 text-[17px] font-bold">{t.byMethod}</h2>
          <ul className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-2.5">
            {data.by_method.map((row) => (
              <li key={row.method} className="rounded-champ bg-voile px-3.5 py-3">
                <span className="block font-semibold">
                  {labels.paymentMethods[row.method as keyof typeof labels.paymentMethods] ??
                    row.method}
                </span>
                <span className="text-[22px] font-extrabold numeric">
                  {netAmount(row.net, currency)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="rounded-carte border border-border bg-card px-5 py-3">
        {data.lines.length === 0 ? (
          <p className="py-4 text-muted-foreground">{t.empty}</p>
        ) : (
          <ul aria-label={t.list}>
            {data.lines.slice(0, shown).map((line) => (
              <CashRow
                key={line.payment_id}
                line={line}
                currency={currency}
                timeZone={timeZone}
                canCancel={canCancel}
              />
            ))}
          </ul>
        )}
        {rest > 0 && (
          <button
            type="button"
            onClick={() => setShown((count) => count + STEP)}
            className="my-2 min-h-cible w-full rounded-champ border-2 border-input bg-card font-bold outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {t.more(Math.min(rest, STEP))}
          </button>
        )}
        {data.truncated && <p className="py-3 text-muted-foreground">{t.truncated}</p>}
      </section>
    </>
  );
}

function Total({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "in" | "out" | "net";
}) {
  return (
    <div
      className={cn(
        "rounded-[20px] px-[18px] py-4",
        tone === "in" && "bg-ventes-teinte",
        tone === "out" && "bg-stock-teinte",
        tone === "net" && "bg-argent text-primary-foreground",
      )}
    >
      <p className="font-semibold">{label}</p>
      <p
        className={cn(
          "text-[28px] font-extrabold numeric",
          tone === "in" && "text-marque",
          tone === "out" && "text-stock-encre",
        )}
      >
        {value}
      </p>
    </div>
  );
}

function CashRow({
  line,
  currency,
  timeZone,
  canCancel,
}: {
  line: Line;
  currency: string;
  timeZone: string;
  canCancel: boolean;
}) {
  const queryClient = useQueryClient();
  const idempotency = useIdempotencyKey();
  const [asking, setAsking] = useState(false);
  const out = isNegative(line.signed_amount);
  const cancellable = canCancel && !line.cancelled && !line.is_reversal && line.method !== "offset";

  const cancel = useMutation({
    meta: { toastError: false },
    mutationFn: (reason: string) =>
      unwrap(
        api.POST("/api/v1/payments/{payment_id}/cancel", {
          params: { path: { payment_id: line.payment_id } },
          body: { reason },
          headers: idempotency.headers,
        }),
      ),
    onSuccess: () => {
      idempotency.renew();
      setAsking(false);
      for (const key of MONEY_KEYS) void queryClient.invalidateQueries({ queryKey: key });
      toast.success(t.cancelledToast);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const Icon = line.is_reversal ? Undo2 : out ? ArrowUpRight : ArrowDownLeft;
  return (
    <li className="border-b border-filet py-3.5 last:border-b-0">
      <div className={cn("flex items-center gap-3.5", line.cancelled && "opacity-55")}>
        <span
          aria-hidden
          className={cn(
            "flex size-11 shrink-0 items-center justify-center rounded-[14px]",
            line.is_reversal
              ? "bg-voile text-encre-2"
              : out
                ? "bg-stock-teinte text-stock-encre"
                : "bg-ventes-teinte text-marque",
          )}
        >
          <Icon className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className={cn("font-bold", line.cancelled && "line-through")}>{cashLineText(line)}</p>
          <p className="text-muted-foreground">{cashLineDetail(line, timeZone)}</p>
        </div>
        <span
          className={cn(
            "text-lg font-extrabold numeric whitespace-nowrap",
            line.cancelled && "line-through",
            line.is_reversal ? "text-encre-2" : out ? "text-stock-encre" : "text-marque",
          )}
        >
          {signedAmount(line.signed_amount, currency)}
        </span>
        {line.cancelled ? (
          <span className="rounded-full bg-voile px-3 py-1.5 text-sm font-bold text-encre-2">
            {t.cancelled}
          </span>
        ) : (
          cancellable &&
          !asking && (
            <button
              type="button"
              onClick={() => setAsking(true)}
              className="min-h-[52px] rounded-champ border-2 border-depenses/25 bg-card px-4 font-bold text-depenses-encre outline-none hover:bg-depenses-teinte focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {t.cancel}
            </button>
          )
        )}
      </div>
      {asking && (
        <div
          role="group"
          aria-label={t.why}
          className="mt-3 flex flex-wrap items-center gap-2 pl-0 sm:pl-[58px]"
        >
          <span className="font-bold text-depenses-encre">{t.why}</span>
          {t.reasons.map((reason) => (
            <button
              key={reason}
              type="button"
              disabled={cancel.isPending}
              onClick={() => cancel.mutate(reason)}
              className="min-h-[50px] rounded-[14px] border-2 border-input bg-card px-4 text-[15px] font-bold outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
            >
              {reason}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setAsking(false)}
            className="min-h-[50px] px-4 text-[15px] font-bold outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {t.keep}
          </button>
          {cancel.isPending && <Loader2 className="size-5 animate-spin" aria-hidden />}
        </div>
      )}
    </li>
  );
}
