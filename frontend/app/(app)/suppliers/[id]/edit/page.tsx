import type { Metadata } from "next";

import { EditPersonPage } from "@/components/people/person-page";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.people.editTitle.supplier };

export default async function EditSupplierPage({ params }: PageProps<"/suppliers/[id]/edit">) {
  const { id } = await params;
  return <EditPersonPage kind="supplier" id={id} />;
}
