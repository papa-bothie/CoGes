import type { Metadata } from "next";

import { labels } from "@/lib/labels";

import { CategoriesView } from "./categories-view";

export const metadata: Metadata = { title: labels.stockScreens.shelves.title };

export default function CategoriesPage() {
  return <CategoriesView />;
}
