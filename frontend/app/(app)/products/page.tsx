import type { Metadata } from "next";
import { Suspense } from "react";

import { labels } from "@/lib/labels";

import { ProductsListView } from "./products-list-view";

export const metadata: Metadata = { title: labels.nav.products };

export default function ProductsPage() {
  return (
    <Suspense>
      <ProductsListView />
    </Suspense>
  );
}
