import type { Metadata } from "next";

import { DeliveryForm } from "@/components/inventory/delivery-form";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.stockScreens.delivery.title };

export default async function ReceivePage({ searchParams }: PageProps<"/inventory/receive">) {
  const { product } = await searchParams;
  return <DeliveryForm productId={typeof product === "string" ? product : undefined} />;
}
