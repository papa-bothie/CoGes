import type { Metadata } from "next";
import { Suspense } from "react";

import { labels } from "@/lib/labels";

import { LabelSheet } from "./label-sheet";

export const metadata: Metadata = { title: labels.products.labelPage.title };

export default async function ProductLabelPage({ params }: PageProps<"/products/[id]/etiquette">) {
  const { id } = await params;
  return (
    <Suspense>
      <LabelSheet productId={id} />
    </Suspense>
  );
}
