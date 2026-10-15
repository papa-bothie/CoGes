import type { Metadata } from "next";
import { Suspense } from "react";

import { labels } from "@/lib/labels";

import { PeopleView } from "./people-view";

export const metadata: Metadata = { title: labels.settingsScreens.nav.people };

export default function SettingsPeoplePage() {
  return (
    <Suspense>
      <PeopleView />
    </Suspense>
  );
}
