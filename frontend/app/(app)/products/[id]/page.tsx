import type { Metadata } from "next";

import { labels } from "@/lib/labels";

import { ProductDetailView } from "./product-detail-view";

export const metadata: Metadata = { title: labels.nav.products };

export default async function ProductPage({ params }: PageProps<"/products/[id]">) {
  const { id } = await params;
  return <ProductDetailView productId={id} />;
}
