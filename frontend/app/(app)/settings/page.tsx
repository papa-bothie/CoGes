import { Settings } from "lucide-react";
import type { Metadata } from "next";

import { PlaceholderPage } from "@/components/placeholder-page";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.nav.settings };

export default function SettingsPage() {
  return <PlaceholderPage title={labels.nav.settings} icon={Settings} />;
}
