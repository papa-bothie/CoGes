import type { Metadata } from "next";
import { Suspense } from "react";

import { labels } from "@/lib/labels";

import { CustomersListView } from "./customers-list-view";

export const metadata: Metadata = { title: labels.nav.customers };

export default function CustomersPage() {
  return (
    <Suspense>
      <CustomersListView />
    </Suspense>
  );
}
