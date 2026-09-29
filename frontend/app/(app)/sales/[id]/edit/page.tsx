import type { Metadata } from "next";

import { labels } from "@/lib/labels";

import { SaleEditor } from "../../sale-editor";

export const metadata: Metadata = { title: labels.nav.sales };

export default async function EditSalePage({ params }: PageProps<"/sales/[id]/edit">) {
  const { id } = await params;
  return <SaleEditor saleId={id} />;
}
