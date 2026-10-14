import type { Metadata } from "next";

import { labels } from "@/lib/labels";

import { ExpensesView } from "./expenses-view";

export const metadata: Metadata = { title: labels.moneyScreens.expensesScreen.title };

export default function ExpensesPage() {
  return <ExpensesView />;
}
