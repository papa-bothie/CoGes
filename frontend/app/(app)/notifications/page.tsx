import { Bell } from "lucide-react";
import type { Metadata } from "next";

import { PlaceholderPage } from "@/components/placeholder-page";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.nav.notifications };

export default function NotificationsPage() {
  return <PlaceholderPage title={labels.nav.notifications} icon={Bell} />;
}
