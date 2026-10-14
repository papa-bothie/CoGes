import type { Metadata } from "next";
import { Suspense } from "react";

import { SettleScreen } from "@/components/finance/settle-screen";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.moneyScreens.collect.title };

export default function Page() {
  return (
    <Suspense>
      <SettleScreen kind="customer" />
    </Suspense>
  );
}
