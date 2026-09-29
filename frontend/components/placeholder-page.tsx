import type { LucideIcon } from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { labels } from "@/lib/labels";

/** Page vide de la phase 11 : valide la coquille et la navigation. */
export function PlaceholderPage({ title, icon }: { title: string; icon: LucideIcon }) {
  return (
    <>
      <PageHeader title={title} />
      <EmptyState icon={icon} title={labels.emptyPage.title} description={labels.emptyPage.body} />
    </>
  );
}
