import type { Metadata } from "next";

import { EditPersonPage } from "@/components/people/person-page";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.people.editTitle.customer };

export default async function EditCustomerPage({ params }: PageProps<"/customers/[id]/edit">) {
  const { id } = await params;
  return <EditPersonPage kind="customer" id={id} />;
}
