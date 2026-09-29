import { Users } from "lucide-react";
import type { Metadata } from "next";

import { PlaceholderPage } from "@/components/placeholder-page";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.nav.customers };

export default function CustomersPage() {
  return <PlaceholderPage title={labels.nav.customers} icon={Users} />;
}
