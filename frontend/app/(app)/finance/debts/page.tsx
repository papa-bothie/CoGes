import type { Metadata } from "next";
import { Suspense } from "react";

import { FinanceSubpage } from "@/components/finance/finance-subpage";
import { labels } from "@/lib/labels";

import { DebtsTab } from "../debts-tab";

export const metadata: Metadata = { title: labels.moneyScreens.allDebts };

/** « Toutes les dettes » : abandon, dette fournisseur saisie à la main (ADR 0073). */
export default function DebtsPage() {
  return (
    <FinanceSubpage title={labels.moneyScreens.allDebts}>
      <Suspense>
        <DebtsTab />
      </Suspense>
    </FinanceSubpage>
  );
}
