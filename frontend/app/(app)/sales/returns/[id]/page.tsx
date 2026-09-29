import type { Metadata } from "next";

import { labels } from "@/lib/labels";

import { ReturnDetailView } from "./return-detail-view";

export const metadata: Metadata = { title: labels.sales.returns };

export default async function ReturnPage({ params }: PageProps<"/sales/returns/[id]">) {
  const { id } = await params;
  return <ReturnDetailView returnId={id} />;
}
