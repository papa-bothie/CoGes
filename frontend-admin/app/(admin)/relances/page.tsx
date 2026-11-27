import type { Metadata } from "next";

import { ReminderList } from "./reminder-list";

export const metadata: Metadata = { title: "À relancer" };

export default function RemindersPage() {
  return <ReminderList />;
}
