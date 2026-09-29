import { LayoutDashboard } from "lucide-react";
import type { Metadata } from "next";

import { PlaceholderPage } from "@/components/placeholder-page";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.nav.dashboard };

export default function DashboardPage() {
  return <PlaceholderPage title={labels.nav.dashboard} icon={LayoutDashboard} />;
}
