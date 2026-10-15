import type { Metadata } from "next";
import { Suspense } from "react";

import { labels } from "@/lib/labels";

import { HistoryView } from "./history-view";

export const metadata: Metadata = { title: labels.settingsScreens.nav.history };

export default function SettingsHistoryPage() {
  return (
    <Suspense>
      <HistoryView />
    </Suspense>
  );
}
