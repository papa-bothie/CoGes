import { BarChart3 } from "lucide-react";
import type { Metadata } from "next";

import { PlaceholderPage } from "@/components/placeholder-page";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.nav.analytics };

export default function AnalyticsPage() {
  return <PlaceholderPage title={labels.nav.analytics} icon={BarChart3} />;
}
