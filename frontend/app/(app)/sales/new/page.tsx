import type { Metadata } from "next";

import { labels } from "@/lib/labels";

import { SaleEditor } from "../sale-editor";

export const metadata: Metadata = { title: labels.sales.newSale };

export default async function NewSalePage({ searchParams }: PageProps<"/sales/new">) {
  const { customer } = await searchParams;
  return <SaleEditor customerId={typeof customer === "string" ? customer : undefined} />;
}
