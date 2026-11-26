"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, MessageCircle, Plus } from "lucide-react";

import { ErrorState } from "@/components/error-state";
import { KitCard } from "@/components/kit/kit-card";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatDateLong } from "@/lib/format";
import { formatAmount } from "@/lib/format/money";
import { labels } from "@/lib/labels";
import {
  ANNUAL_DISCOUNT_PERCENT,
  BUSINESS,
  BUSINESS_EXTRAS,
  FEATURE_LABELS,
  type FeatureCode,
  OFFRES,
  type PlanCode,
  amount,
  payLink,
  quoteLink,
  upgradeLink,
} from "@/lib/offres";

const t = labels.settingsScreens.subscription;

type Subscription = Schemas["SubscriptionRead"];

/** La ligne d'état, en mots simples. */
export function statusLine(subscription: Subscription, timeZone: string): string {
  if (subscription.is_license) return t.license(subscription.name);
  switch (subscription.status) {
    case "trial":
      return t.trial(formatDateLong(subscription.trial_ends_at, timeZone));
    case "active":
      return subscription.current_period_end
        ? t.paidUntil(formatDateLong(subscription.current_period_end, timeZone))
        : t.active;
    case "past_due":
      return subscription.current_period_end
        ? t.pastDue(formatDateLong(subscription.current_period_end, timeZone))
        : t.pastDueNoDay;
    case "suspended":
      return t.suspended;
  }
}

const linkButton =
  "inline-flex min-h-cible items-center justify-center gap-2 rounded-champ px-5 font-bold outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

function FeatureList({ codes, icon }: { codes: readonly FeatureCode[]; icon: "check" | "plus" }) {
  const Icon = icon === "check" ? Check : Plus;
  return (
    <ul className="flex flex-col gap-2">
      {codes.map((code) => (
        <li key={code} className="flex items-start gap-2.5">
          <Icon className="mt-0.5 size-5 shrink-0 text-ventes-encre" aria-hidden />
          <span>{FEATURE_LABELS[code]}</span>
        </li>
      ))}
    </ul>
  );
}

/** « Mon abonnement » (prompt 41, B4, ADR 0132) : réservé au gérant (`company:update`). */
export function SubscriptionView() {
  const { timeZone } = useCompanyLocale();
  const query = useQuery({
    queryKey: queryKeys.subscription,
    queryFn: () => unwrap(api.GET("/api/v1/subscription")),
  });
  if (query.isPending) return <Skeleton className="h-64 rounded-carte" />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const subscription = query.data;
  const plan = OFFRES.find((item) => item.code === (subscription.code as PlanCode));
  const included = (plan?.features ?? []).filter((code) => subscription.features.includes(code));
  const acquiredImports = subscription.extra_features.includes("imports");
  const acquiredAccounts =
    plan && subscription.max_users !== null && subscription.max_users > plan.maxUsers
      ? subscription.max_users
      : null;
  const extras = BUSINESS_EXTRAS.filter((code) => !subscription.features.includes(code));
  const payable = !subscription.is_license && plan?.monthly != null && plan.annual != null;

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-titre-carte">{t.title}</h2>

      <KitCard>
        <p className="text-2xl font-extrabold">{t.offer(subscription.name)}</p>
        <p className="mt-1 font-bold text-encre-2" data-testid="subscription-status">
          {statusLine(subscription, timeZone)}
        </p>
        <p className="mt-1 text-encre-2">
          {t.accounts(subscription.active_users, subscription.max_users)}
        </p>
        {(acquiredImports || acquiredAccounts !== null) && (
          <div className="mt-4 rounded-champ bg-ventes-teinte p-3.5 text-ventes-encre">
            <p className="font-bold">{t.acquired}</p>
            <ul className="mt-1 list-disc pl-5">
              {acquiredImports && <li>{t.acquiredImports}</li>}
              {acquiredAccounts !== null && <li>{t.acquiredAccounts(acquiredAccounts)}</li>}
            </ul>
          </div>
        )}
      </KitCard>

      <KitCard title={t.contains}>
        <FeatureList codes={included} icon="check" />
      </KitCard>

      {subscription.code === "starter" && extras.length > 0 && (
        <KitCard title={t.businessAdds(BUSINESS.name)}>
          <FeatureList codes={extras} icon="plus" />
          <a
            href={upgradeLink()}
            target="_blank"
            rel="noopener noreferrer"
            className={`${linkButton} mt-4 bg-primary text-primary-foreground hover:bg-primary/90`}
          >
            <MessageCircle className="size-5" aria-hidden />
            {t.upgrade(BUSINESS.name)}
          </a>
        </KitCard>
      )}

      {!subscription.is_license && (
        <KitCard title={t.howToPay}>
          <p className="text-encre-2">{t.howToPayHint}</p>
          {payable && plan ? (
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <PayOption
                price={formatAmount(amount(plan.monthly!))}
                period={t.perMonth}
                href={payLink(plan.name, 1)}
                action={t.payMonth}
              />
              <PayOption
                price={formatAmount(amount(plan.annual!))}
                period={t.perYear(ANNUAL_DISCOUNT_PERCENT)}
                href={payLink(plan.name, 12)}
                action={t.payYear}
              />
            </div>
          ) : (
            <div className="mt-4 flex flex-col gap-3">
              <p className="font-bold">{t.quote}</p>
              <a
                href={quoteLink()}
                target="_blank"
                rel="noopener noreferrer"
                className={`${linkButton} self-start border-2 border-input bg-card`}
              >
                <MessageCircle className="size-5" aria-hidden />
                {t.quoteButton}
              </a>
            </div>
          )}
        </KitCard>
      )}
    </div>
  );
}

function PayOption({
  price,
  period,
  href,
  action,
}: {
  price: string;
  period: string;
  href: string;
  action: string;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-champ border border-border p-3.5">
      <p>
        <span className="text-xl font-extrabold numeric">{price}</span>{" "}
        <span className="text-encre-2">{period}</span>
      </p>
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className={`${linkButton} bg-primary text-primary-foreground hover:bg-primary/90`}
      >
        <MessageCircle className="size-5" aria-hidden />
        {action}
      </a>
    </div>
  );
}
