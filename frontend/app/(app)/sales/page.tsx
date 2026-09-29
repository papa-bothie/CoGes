import { ShoppingCart } from "lucide-react";
import type { Metadata } from "next";

import { PlaceholderPage } from "@/components/placeholder-page";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.nav.sales };

export default function SalesPage() {
  return <PlaceholderPage title={labels.nav.sales} icon={ShoppingCart} />;
}
