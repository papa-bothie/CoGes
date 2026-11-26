import type { Metadata } from "next";

import { labels } from "@/lib/labels";

import { SubscriptionView } from "./subscription-view";

export const metadata: Metadata = { title: labels.settingsScreens.nav.subscription };

export default function SettingsSubscriptionPage() {
  return <SubscriptionView />;
}
