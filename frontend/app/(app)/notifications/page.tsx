import type { Metadata } from "next";
import { Suspense } from "react";

import { labels } from "@/lib/labels";

import { NotificationsView } from "./notifications-view";

export const metadata: Metadata = { title: labels.nav.notifications };

export default function NotificationsPage() {
  return (
    <Suspense>
      <NotificationsView />
    </Suspense>
  );
}
