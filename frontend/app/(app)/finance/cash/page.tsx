import type { Metadata } from "next";
import { Suspense } from "react";

import { labels } from "@/lib/labels";

import { CashView } from "./cash-view";

export const metadata: Metadata = { title: labels.moneyScreens.cash.title };

export default function CashPage() {
  return (
    <Suspense>
      <CashView />
    </Suspense>
  );
}
