import type { Metadata } from "next";

import { NewPersonPage } from "@/components/people/person-page";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.people.addTitle };

export default function NewCustomerPage() {
  return <NewPersonPage initialKind="customer" />;
}
