import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { labels } from "@/lib/labels";

import { MoneyView } from "./money-view";

export const metadata: Metadata = { title: labels.moneyScreens.title };

/** Les anciens onglets de L'argent (avant le lot 3d) mènent à leur nouvelle page. */
const OLD_TABS: Record<string, string> = {
  overview: "/finance",
  payments: "/finance/cash",
  debts: "/finance/debts",
  expenses: "/finance/expenses/all",
};

export default async function FinancePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const tab = typeof params.tab === "string" ? params.tab : null;
  if (tab && OLD_TABS[tab] && OLD_TABS[tab] !== "/finance") {
    const rest = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (key !== "tab" && typeof value === "string") rest.set(key, value);
    }
    const query = rest.toString();
    redirect(`${OLD_TABS[tab]}${query ? `?${query}` : ""}`);
  }
  return (
    <Suspense>
      <MoneyView />
    </Suspense>
  );
}
