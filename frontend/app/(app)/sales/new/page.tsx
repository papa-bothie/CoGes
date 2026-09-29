import type { Metadata } from "next";

import { labels } from "@/lib/labels";

import { SaleEditor } from "../sale-editor";

export const metadata: Metadata = { title: labels.sales.newSale };

export default function NewSalePage() {
  return <SaleEditor />;
}
