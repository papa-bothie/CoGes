import type { Metadata } from "next";
import { Suspense } from "react";

import { labels } from "@/lib/labels";

import { ReceiptView } from "./receipt-view";

export const metadata: Metadata = { title: labels.sales.receipt };

export default async function ReceiptPage({ params }: PageProps<"/sales/[id]/receipt">) {
  const { id } = await params;
  return (
    <Suspense>
      <ReceiptView saleId={id} />
    </Suspense>
  );
}
