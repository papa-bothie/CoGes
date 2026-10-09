import type { Metadata } from "next";

import { labels } from "@/lib/labels";

import { ReturnSlipView } from "./return-slip-view";

export const metadata: Metadata = { title: labels.sales.returns };

export default async function ReturnSlipPage({ params }: PageProps<"/sales/returns/[id]/receipt">) {
  const { id } = await params;
  return <ReturnSlipView returnId={id} />;
}
