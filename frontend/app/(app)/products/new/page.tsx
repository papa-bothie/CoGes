import type { Metadata } from "next";

import { labels } from "@/lib/labels";

import { NewProductForm } from "./new-product-form";

export const metadata: Metadata = { title: labels.products.newForm.title };

export default function NewProductPage() {
  return <NewProductForm />;
}
