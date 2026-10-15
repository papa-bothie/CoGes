import type { Metadata } from "next";
import { Suspense } from "react";

import { labels } from "@/lib/labels";

import { RightsView } from "./rights-view";

export const metadata: Metadata = { title: labels.settingsScreens.nav.rights };

export default function SettingsRightsPage() {
  return (
    <Suspense>
      <RightsView />
    </Suspense>
  );
}
