import type { Metadata } from "next";
import { Suspense } from "react";

import { labels } from "@/lib/labels";

import { SuppliersListView } from "./suppliers-list-view";

export const metadata: Metadata = { title: labels.nav.suppliers };

export default function SuppliersPage() {
  return (
    <Suspense>
      <SuppliersListView />
    </Suspense>
  );
}
