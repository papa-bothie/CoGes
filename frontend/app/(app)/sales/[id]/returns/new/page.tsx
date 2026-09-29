import type { Metadata } from "next";

import { labels } from "@/lib/labels";

import { ReturnForm } from "./return-form";

export const metadata: Metadata = { title: labels.sales.makeReturn };

export default async function NewReturnPage({ params }: PageProps<"/sales/[id]/returns/new">) {
  const { id } = await params;
  return <ReturnForm saleId={id} />;
}
