import type { Metadata } from "next";

import { labels } from "@/lib/labels";

import { CustomerDetailView } from "./customer-detail-view";

export const metadata: Metadata = { title: labels.nav.customers };

export default async function CustomerPage({ params }: PageProps<"/customers/[id]">) {
  const { id } = await params;
  return <CustomerDetailView customerId={id} />;
}
