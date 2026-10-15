import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { labels } from "@/lib/labels";

import { ShopView } from "./shop-view";

export const metadata: Metadata = { title: labels.settingsScreens.title };

/** Les anciens onglets (`?tab=`) mènent à leur rubrique (ADR 0075). */
const LEGACY_TABS: Record<string, string> = {
  users: "/settings/people",
  roles: "/settings/rights",
  audit: "/settings/history",
};

export default async function SettingsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { tab } = await searchParams;
  const target = typeof tab === "string" ? LEGACY_TABS[tab] : undefined;
  if (target) redirect(target);
  return (
    <Suspense>
      <ShopView />
    </Suspense>
  );
}
