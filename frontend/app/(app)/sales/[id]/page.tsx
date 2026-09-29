import type { Metadata } from "next";

import { labels } from "@/lib/labels";

import { SaleDetailView } from "./sale-detail-view";

export const metadata: Metadata = { title: labels.nav.sales };

export default async function SalePage({ params }: PageProps<"/sales/[id]">) {
  const { id } = await params;
  return <SaleDetailView saleId={id} />;
}
