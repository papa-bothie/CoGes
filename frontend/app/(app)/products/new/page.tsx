import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";
import { labels } from "@/lib/labels";

import { ProductForm } from "../product-form";

export const metadata: Metadata = { title: labels.products.newTitle };

export default function NewProductPage() {
  return (
    <>
      <PageHeader title={labels.products.newTitle} />
      <ProductForm />
    </>
  );
}
