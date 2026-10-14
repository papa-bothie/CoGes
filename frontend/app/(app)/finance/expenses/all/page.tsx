import type { Metadata } from "next";
import { Suspense } from "react";

import { FinanceSubpage } from "@/components/finance/finance-subpage";
import { PeriodPicker } from "@/components/period/period-picker";
import { labels } from "@/lib/labels";

import { ExpensesTab } from "../../expenses-tab";

const t = labels.moneyScreens.expensesScreen;

export const metadata: Metadata = { title: t.allExpenses };

/** « Toutes les dépenses » : la liste par période, derrière l'écran 20 (ADR 0073). */
export default function AllExpensesPage() {
  return (
    <Suspense>
      <FinanceSubpage
        title={t.allExpenses}
        backHref="/finance/expenses"
        backLabel={t.title}
        actions={<PeriodPicker />}
      >
        <ExpensesTab />
      </FinanceSubpage>
    </Suspense>
  );
}
