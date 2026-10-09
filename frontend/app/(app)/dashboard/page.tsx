import type { Metadata } from "next";

import { labels } from "@/lib/labels";

import { DashboardView } from "./dashboard-view";

export const metadata: Metadata = { title: labels.dashboard.title };

export default function DashboardPage() {
  return <DashboardView />;
}
