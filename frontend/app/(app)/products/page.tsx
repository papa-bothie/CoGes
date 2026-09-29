import { Package } from "lucide-react";
import type { Metadata } from "next";

import { PlaceholderPage } from "@/components/placeholder-page";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.nav.products };

export default function ProductsPage() {
  return <PlaceholderPage title={labels.nav.products} icon={Package} />;
}
