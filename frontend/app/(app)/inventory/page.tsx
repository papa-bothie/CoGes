import type { Metadata } from "next";
import { Suspense } from "react";

import { labels } from "@/lib/labels";

import { InventoryView } from "./inventory-view";

export const metadata: Metadata = { title: labels.stockScreens.list.journal };

export default function InventoryPage() {
  return (
    <Suspense>
      <InventoryView />
    </Suspense>
  );
}
