import { Boxes } from "lucide-react";
import type { Metadata } from "next";

import { PlaceholderPage } from "@/components/placeholder-page";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.nav.inventory };

export default function InventoryPage() {
  return <PlaceholderPage title={labels.nav.inventory} icon={Boxes} />;
}
