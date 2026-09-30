import type { Metadata } from "next";
import { Suspense } from "react";

import { labels } from "@/lib/labels";

import { InsightsView } from "./insights-view";

export const metadata: Metadata = { title: labels.nav.insights };

export default function InsightsPage() {
  return (
    <Suspense>
      <InsightsView />
    </Suspense>
  );
}
