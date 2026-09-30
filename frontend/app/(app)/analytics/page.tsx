import type { Metadata } from "next";
import { Suspense } from "react";

import { labels } from "@/lib/labels";

import { AnalyticsView } from "./analytics-view";

export const metadata: Metadata = { title: labels.nav.analytics };

export default function AnalyticsPage() {
  return (
    <Suspense>
      <AnalyticsView />
    </Suspense>
  );
}
