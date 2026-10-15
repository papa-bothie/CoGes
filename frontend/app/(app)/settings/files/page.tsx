import type { Metadata } from "next";
import { Suspense } from "react";

import { labels } from "@/lib/labels";

import { FilesView } from "./files-view";

export const metadata: Metadata = { title: labels.settingsScreens.nav.files };

export default function SettingsFilesPage() {
  return (
    <Suspense>
      <FilesView />
    </Suspense>
  );
}
