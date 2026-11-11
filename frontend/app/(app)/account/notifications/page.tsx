import type { Metadata } from "next";

import { labels } from "@/lib/labels";

import { PushView } from "./push-view";

export const metadata: Metadata = { title: labels.push.title };

export default function PushPage() {
  return <PushView />;
}
