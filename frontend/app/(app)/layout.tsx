import { AppShell } from "@/components/shell/app-shell";

export default function ProtectedLayout({ children }: LayoutProps<"/">) {
  return <AppShell>{children}</AppShell>;
}
