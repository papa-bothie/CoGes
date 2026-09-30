import type { Metadata } from "next";

import { labels } from "@/lib/labels";

import { EditProductView } from "./edit-product-view";

export const metadata: Metadata = { title: labels.nav.products };

export default async function EditProductPage({ params }: PageProps<"/products/[id]/edit">) {
  const { id } = await params;
  return <EditProductView productId={id} />;
}
