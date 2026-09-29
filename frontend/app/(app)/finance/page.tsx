import { Wallet } from "lucide-react";
import type { Metadata } from "next";

import { PlaceholderPage } from "@/components/placeholder-page";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.nav.finance };

export default function FinancePage() {
  return <PlaceholderPage title={labels.nav.finance} icon={Wallet} />;
}
