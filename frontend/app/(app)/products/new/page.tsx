import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";
import { labels } from "@/lib/labels";

import { NewProductForm } from "./new-product-form";

export const metadata: Metadata = { title: labels.products.newForm.title };

export default function NewProductPage() {
  return (
    <>
      <PageHeader title={labels.products.newForm.title} />
      <NewProductForm />
    </>
  );
}
