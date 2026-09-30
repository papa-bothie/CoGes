import type { Metadata } from "next";

import { labels } from "@/lib/labels";

import { CategoriesView } from "./categories-view";

export const metadata: Metadata = { title: labels.categories.title };

export default function CategoriesPage() {
  return <CategoriesView />;
}
