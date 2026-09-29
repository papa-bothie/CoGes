import { Sparkles } from "lucide-react";
import type { Metadata } from "next";

import { PlaceholderPage } from "@/components/placeholder-page";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.nav.insights };

export default function InsightsPage() {
  return <PlaceholderPage title={labels.nav.insights} icon={Sparkles} />;
}
