"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowDownLeft, ArrowUpRight, Menu, Plus, Wallet, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { ErrorState } from "@/components/error-state";
import { MoneyBars } from "@/components/finance/money-bars";
import { Chip } from "@/components/kit/chip";
import { KitCard } from "@/components/kit/kit-card";
import { Avatar } from "@/components/kit/list-row";
import { RUBRIQUE_CLASSES } from "@/components/kit/rubrique";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatAmount, formatDate, formatFigure } from "@/lib/format";
import { labels } from "@/lib/labels";
import {
  absolute,
  bucketLabel,
  daysUntil,
  DUE_SOON_DAYS,
  isNegative,
  paidDay,
  signedAmount,
} from "@/lib/money";
import { todayIn } from "@/lib/period";
import { dueDay } from "@/lib/people";
import { cn } from "@/lib/utils";

const t = labels.moneyScreens;
type Period = Schemas["MoneyPeriod"];
const PERIODS: readonly Period[] = ["today", "week", "month"];
const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Poids d'une barre : la partie entière du montant, pour la hauteur seulement. */
function weight(value: string): number {
  return Number(absolute(value).split(".")[0] ?? "0");
}

/**
 * L'argent, maquette v2 (écrans 17 et 17b) : gagné ou perdu sur la période, l'équation
 * vendu − prix d'achat − dépenses, la caisse et son graphique, puis ce que doivent les
 * clients et ce qu'on doit aux fournisseurs. La période vit dans l'URL ; « Choisir des
 * dates » reste en secondaire (ADR 0073).
 */
export function MoneyView() {
  const { currency, timeZone } = useCompanyLocale();
  const table = useTableParams();
  const from = table.get("from");
  const to = table.get("to");
  const custom = !!from && !!to && DATE.test(from) && DATE.test(to) && from <= to;
  const requested = table.get("period") as Period | null;
  const period: Period | null = custom ? null : PERIODS.includes(requested!) ? requested : "month";
  const [choosing, setChoosing] = useState(custom);
  const today = todayIn(timeZone);

  const params = custom ? { from: from!, to: to! } : { period: period! };
  const money = useQuery({
    queryKey: queryKeys.analytics.money(params),
    queryFn: () => unwrap(api.GET("/api/v1/analytics/money", { params: { query: params } })),
  });

  const choose = (next: Period) => {
    setChoosing(false);
    table.replaceAll(next === "month" ? {} : { period: next });
  };
  const setRange = (nextFrom: string, nextTo: string) =>
    table.replaceAll({ from: nextFrom, to: nextTo });

  return (
    <div className="mx-auto flex max-w-page flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{t.title}</h1>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button
            type="button"
            aria-expanded={choosing}
            onClick={() => setChoosing((on) => !on)}
            className="min-h-11 px-2 font-semibold text-argent-encre underline-offset-4 hover:underline pointer-coarse:min-h-12"
          >
            {t.chooseDates}
          </button>
          <div role="group" aria-label={t.title} className="flex flex-wrap gap-2">
            {PERIODS.map((item) => (
              <Chip
                key={item}
                rubrique="argent"
                tone="plein"
                selected={period === item}
                onClick={() => choose(item)}
                className="min-h-[50px]"
              >
                {t.periods[item]}
              </Chip>
            ))}
          </div>
        </div>
      </div>
      {choosing && (
        <div className="flex flex-wrap items-end justify-end gap-3">
          {(["from", "to"] as const).map((bound) => (
            <label key={bound} className="flex flex-col gap-1 font-semibold">
              {t[bound]}
              <input
                type="date"
                value={(bound === "from" ? from : to) ?? ""}
                max={today}
                onChange={(event) => {
                  const value = event.target.value;
                  if (!DATE.test(value)) return;
                  const other = (bound === "from" ? to : from) ?? value;
                  if (bound === "from") setRange(value, other < value ? value : other);
                  else setRange(other > value ? value : other, value);
                }}
                className="min-h-cible rounded-champ border-2 border-input bg-card px-3 text-foreground outline-none focus-visible:border-argent"
              />
            </label>
          ))}
        </div>
      )}

      <Shortcuts />

      {money.isError ? (
        <ErrorState error={money.error} onRetry={() => void money.refetch()} />
      ) : !money.data ? (
        <Skeleton className="h-[640px] w-full rounded-carte" />
      ) : (
        <MoneyBody data={money.data} currency={currency} today={today} timeZone={timeZone} />
      )}
    </div>
  );
}

const SHORTCUTS: readonly {
  href: string;
  label: string;
  icon: LucideIcon;
  tone: string;
  permission: Parameters<typeof usePermission>[0];
}[] = [
  {
    href: "/finance/collect",
    label: t.shortcuts.collect,
    icon: ArrowDownLeft,
    tone: "border-clients/20 bg-clients-teinte [&_svg]:text-clients-encre",
    permission: "payments:create",
  },
  {
    href: "/finance/pay",
    label: t.shortcuts.pay,
    icon: ArrowUpRight,
    tone: "border-argent/20 bg-argent-teinte [&_svg]:text-argent-encre",
    permission: "payments:create",
  },
  {
    href: "/finance/expenses",
    label: t.shortcuts.expense,
    icon: Plus,
    tone: "border-depenses/20 bg-depenses-teinte [&_svg]:text-depenses-encre",
    permission: "expenses:read",
  },
  {
    href: "/finance/cash",
    label: t.shortcuts.cash,
    icon: Menu,
    tone: "border-border bg-card [&_svg]:text-encre-2",
    permission: "analytics:read",
  },
];

function Shortcut({ item }: { item: (typeof SHORTCUTS)[number] }) {
  const allowed = usePermission(item.permission);
  if (!allowed) return null;
  return (
    <Link
      href={item.href}
      className={cn(
        "flex min-h-[76px] items-center gap-3.5 rounded-carte border p-4 text-[17px] font-bold text-foreground",
        "outline-none hover:brightness-[0.98] focus-visible:ring-3 focus-visible:ring-ring/50",
        item.tone,
      )}
    >
      <item.icon className="size-7 shrink-0" aria-hidden />
      {item.label}
    </Link>
  );
}

function Shortcuts() {
  return (
    <nav
      aria-label={t.title}
      className="grid grid-cols-[repeat(auto-fit,minmax(210px,1fr))] gap-2.5"
    >
      {SHORTCUTS.map((item) => (
        <Shortcut key={item.href} item={item} />
      ))}
    </nav>
  );
}

function MoneyBody({
  data,
  currency,
  today,
  timeZone,
}: {
  data: Schemas["MoneyOverview"];
  currency: string;
  today: string;
  timeZone: string;
}) {
  const lost = isNegative(data.result);
  const when = data.period
    ? t.when[data.period]
    : t.when.range(formatDate(data.period_from, timeZone), formatDate(data.period_to, timeZone));
  const biggest = data.biggest_expense;
  const operator = (sign: string, name: string) => (
    <span className="self-center text-[28px] font-extrabold text-muted-foreground" aria-hidden>
      <span className="sr-only">{name}</span>
      {sign}
    </span>
  );
  return (
    <>
      <KitCard className="flex flex-col gap-[18px] p-[26px]">
        <div>
          <p className="text-lg font-semibold text-muted-foreground">{t.youHave(when)}</p>
          <p className={cn("font-extrabold", lost ? "text-stock-encre" : "text-marque")}>
            <span className="text-[30px]">{lost ? t.lost : t.won}</span>{" "}
            <span className="text-[40px] leading-tight numeric sm:text-[52px]">
              {formatAmount(absolute(data.result), currency)}
            </span>
          </p>
          {lost && biggest && (
            <p className="mt-1 text-[17px] font-bold text-stock-encre">
              {t.because(
                biggest.label,
                paidDay(biggest.spent_at, today),
                formatAmount(biggest.amount, currency),
              )}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <EquationBlock label={t.sold} value={data.sold} currency={currency} tone="ventes" />
          {operator("−", t.minus)}
          <EquationBlock label={t.cogs} value={data.cogs} currency={currency} tone="stock" />
          {operator("−", t.minus)}
          <EquationBlock
            label={t.expenses}
            value={data.expenses}
            currency={currency}
            tone="depenses"
          />
          {operator("=", t.equals)}
          <EquationBlock
            label={lost ? t.lostBlock : t.wonBlock}
            value={absolute(data.result)}
            currency={currency}
            tone={lost ? "perte" : "gain"}
          />
        </div>
      </KitCard>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-4">
        <CashCard
          label={t.cashIn}
          value={formatAmount(data.cash_in, currency)}
          icon={ArrowDownLeft}
          className="border-ventes/20 bg-ventes-teinte"
          disc="bg-primary text-primary-foreground"
          ink="text-marque"
        />
        <CashCard
          label={t.cashOut}
          value={formatAmount(data.cash_out, currency)}
          icon={ArrowUpRight}
          className="border-stock/20 bg-stock-teinte"
          disc="bg-stock text-primary-foreground"
          ink="text-stock-encre"
        />
        <CashCard
          label={t.difference}
          value={signedAmount(data.net_cash, currency)}
          icon={Wallet}
          className="border-argent bg-argent text-primary-foreground"
          disc="bg-card text-argent"
          ink=""
        />
      </div>

      <KitCard
        title={t.chart[data.grain]}
        action={
          <div aria-hidden className="flex gap-4 font-semibold">
            <span className="flex items-center gap-2">
              <span className="size-4 rounded-[5px] bg-primary" />
              {t.legendIn}
            </span>
            <span className="flex items-center gap-2">
              <span className="size-4 rounded-[5px] bg-barre-sortie" />
              {t.legendOut}
            </span>
          </div>
        }
      >
        <MoneyBars
          label={t.chart[data.grain]}
          inLabel={t.legendIn}
          outLabel={t.legendOut}
          groups={data.buckets.map((bucket) => ({
            label: bucketLabel(bucket, data.grain),
            inDisplay: formatFigure(bucket.cash_in, currency),
            outDisplay: formatFigure(bucket.cash_out, currency),
            inWeight: weight(bucket.cash_in),
            outWeight: weight(bucket.cash_out),
          }))}
        />
      </KitCard>

      {(data.receivables || data.payables) && (
        <div className="flex flex-wrap gap-5">
          {data.receivables && (
            <OwedCard
              title={t.customersOwe}
              summary={data.receivables}
              currency={currency}
              rubrique="clients"
              empty={t.nobodyOwes}
              actionHref="/finance/collect"
              actionLabel={t.shortcuts.collect}
              detail={() => null}
              rowHref={(id) => `/finance/collect?customer=${id}`}
            />
          )}
          {data.payables && (
            <OwedCard
              title={t.youOweSuppliers}
              summary={data.payables}
              currency={currency}
              rubrique="argent"
              empty={t.youOweNobody}
              actionHref="/finance/pay"
              actionLabel={t.shortcuts.pay}
              detail={(row) =>
                row.due_date ? (
                  <span
                    className={cn(
                      daysUntil(row.due_date, today) <= DUE_SOON_DAYS
                        ? "font-semibold text-stock-encre"
                        : "text-muted-foreground",
                    )}
                  >
                    {t.payBefore(dueDay(row.due_date))}
                  </span>
                ) : null
              }
              rowHref={(id) => `/finance/pay?supplier=${id}`}
            />
          )}
        </div>
      )}
    </>
  );
}

const BLOCKS = {
  ventes: { box: "bg-ventes-teinte", value: "text-marque", label: "" },
  stock: { box: "bg-stock-teinte", value: "text-stock-encre", label: "" },
  depenses: { box: "bg-depenses-teinte", value: "text-depenses-encre", label: "" },
  gain: { box: "bg-primary text-primary-foreground", value: "", label: "" },
  perte: { box: "bg-stock text-primary-foreground", value: "", label: "" },
} as const;

function EquationBlock({
  label,
  value,
  currency,
  tone,
}: {
  label: string;
  value: string;
  currency: string;
  tone: keyof typeof BLOCKS;
}) {
  return (
    <div
      className={cn(
        "flex flex-[1_1_170px] flex-col gap-1 rounded-[18px] px-[18px] py-4",
        BLOCKS[tone].box,
      )}
    >
      <span className="font-semibold">{label}</span>
      <span className={cn("text-[22px] font-extrabold numeric", BLOCKS[tone].value)}>
        {formatAmount(value, currency)}
      </span>
    </div>
  );
}

function CashCard({
  label,
  value,
  icon: Icon,
  className,
  disc,
  ink,
}: {
  label: string;
  value: string;
  icon: LucideIcon;
  className: string;
  disc: string;
  ink: string;
}) {
  return (
    <div className={cn("flex items-center gap-4 rounded-carte border p-carte", className)}>
      <span
        aria-hidden
        className={cn("flex size-[52px] shrink-0 items-center justify-center rounded-champ", disc)}
      >
        <Icon className="size-6" />
      </span>
      <div className="min-w-0">
        <p className="font-semibold">{label}</p>
        <p className={cn("text-[28px] leading-tight font-extrabold numeric", ink)}>{value}</p>
      </div>
    </div>
  );
}

type Owed = Schemas["OwedSummary"];

function OwedCard({
  title,
  summary,
  currency,
  rubrique,
  empty,
  actionHref,
  actionLabel,
  detail,
  rowHref,
}: {
  title: string;
  summary: Owed;
  currency: string;
  rubrique: "clients" | "argent";
  empty: string;
  actionHref: string;
  actionLabel: string;
  detail: (row: Owed["rows"][number]) => ReactNode;
  rowHref: (id: string) => string;
}) {
  const tone = RUBRIQUE_CLASSES[rubrique];
  return (
    <KitCard
      className="flex flex-[1_1_380px] flex-col"
      title={title}
      action={
        <span className={cn("text-[22px] font-extrabold numeric", tone.ink)}>
          {formatAmount(summary.total, currency)}
        </span>
      }
    >
      {summary.rows.length === 0 ? (
        <p className="text-muted-foreground">{empty}</p>
      ) : (
        <ul>
          {summary.rows.map((row) => (
            <li key={row.id}>
              <Link
                href={rowHref(row.id)}
                className="flex min-h-[66px] items-center gap-3.5 border-t border-filet py-3 text-foreground outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                <Avatar name={row.name} rubrique={rubrique} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-bold">{row.name}</span>
                  {detail(row)}
                </span>
                <span className="font-extrabold numeric">{formatAmount(row.owed, currency)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {summary.count > 0 && (
        <Link
          href={actionHref}
          className={cn(
            "mt-4 flex min-h-[52px] items-center justify-center rounded-bouton text-[17px] font-bold",
            "outline-none hover:opacity-90 focus-visible:ring-3 focus-visible:ring-ring/50",
            tone.solid,
          )}
        >
          {actionLabel}
        </Link>
      )}
    </KitCard>
  );
}
