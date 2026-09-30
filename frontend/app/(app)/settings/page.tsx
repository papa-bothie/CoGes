import type { Metadata } from "next";
import { Suspense } from "react";

import { labels } from "@/lib/labels";

import { SettingsView } from "./settings-view";

export const metadata: Metadata = { title: labels.nav.settings };

export default function SettingsPage() {
  return (
    <Suspense>
      <SettingsView />
    </Suspense>
  );
}
