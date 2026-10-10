import type { Metadata } from "next";

import { StockCorrection } from "@/components/inventory/stock-correction";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.stock.correction.title };

export default async function AdjustPage({ searchParams }: PageProps<"/inventory/adjust">) {
  const { product } = await searchParams;
  return <StockCorrection productId={typeof product === "string" ? product : undefined} />;
}
