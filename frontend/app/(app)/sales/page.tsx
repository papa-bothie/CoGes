import type { Metadata } from "next";
import { Suspense } from "react";

import { labels } from "@/lib/labels";

import { SalesListView } from "./sales-list-view";

export const metadata: Metadata = { title: labels.nav.sales };

export default function SalesPage() {
  return (
    <Suspense>
      <SalesListView />
    </Suspense>
  );
}
