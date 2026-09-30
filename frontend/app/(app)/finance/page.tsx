import type { Metadata } from "next";
import { Suspense } from "react";

import { labels } from "@/lib/labels";

import { FinanceView } from "./finance-view";

export const metadata: Metadata = { title: labels.nav.finance };

export default function FinancePage() {
  return (
    <Suspense>
      <FinanceView />
    </Suspense>
  );
}
