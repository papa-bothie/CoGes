import type { Metadata } from "next";
import { Suspense } from "react";

import { PeopleListView } from "@/components/people/people-list-view";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.peopleScreens.list.title.supplier };

export default function SuppliersPage() {
  return (
    <Suspense>
      <PeopleListView kind="supplier" />
    </Suspense>
  );
}
