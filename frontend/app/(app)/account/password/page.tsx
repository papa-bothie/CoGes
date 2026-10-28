import type { Metadata } from "next";

import { labels } from "@/lib/labels";

import { ChangePasswordView } from "./change-password-view";

export const metadata: Metadata = { title: labels.accountPassword.title };

export default function ChangePasswordPage() {
  return <ChangePasswordView />;
}
