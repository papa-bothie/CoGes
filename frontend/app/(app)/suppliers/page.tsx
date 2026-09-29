import { Truck } from "lucide-react";
import type { Metadata } from "next";

import { PlaceholderPage } from "@/components/placeholder-page";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.nav.suppliers };

export default function SuppliersPage() {
  return <PlaceholderPage title={labels.nav.suppliers} icon={Truck} />;
}
