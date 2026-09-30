import type { Metadata } from "next";

import { labels } from "@/lib/labels";

import { SupplierDetailView } from "./supplier-detail-view";

export const metadata: Metadata = { title: labels.nav.suppliers };

export default async function SupplierPage({ params }: PageProps<"/suppliers/[id]">) {
  const { id } = await params;
  return <SupplierDetailView supplierId={id} />;
}
