"use client";

import { PageHeader } from "@/components/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMe } from "@/hooks/use-me";
import { useTableParams } from "@/hooks/use-table-params";
import { labels } from "@/lib/labels";
import { can, type PermissionCode } from "@/lib/permissions";

import { AuditTab } from "./audit-tab";
import { CompanyTab } from "./company-tab";
import { RolesTab } from "./roles-tab";
import { UsersTab } from "./users-tab";

const TABS = [
  { id: "company", permission: "company:read" },
  { id: "users", permission: "users:read" },
  { id: "roles", permission: "roles:read" },
  { id: "audit", permission: "audit:read" },
] as const satisfies readonly { id: string; permission: PermissionCode }[];

type Tab = (typeof TABS)[number]["id"];

/**
 * Paramètres : chaque onglet n'apparaît qu'avec son droit de lecture. Le serveur revérifie
 * tout (un vendeur reçoit 403 sur chacune de ces routes).
 */
export function SettingsView() {
  const table = useTableParams();
  const { data: me } = useMe();
  const visible = TABS.filter((tab) => can(me?.permissions, tab.permission));
  const requested = table.get("tab");
  const tab: Tab | undefined = visible.find((item) => item.id === requested)?.id ?? visible[0]?.id;

  return (
    <>
      <PageHeader title={labels.nav.settings} />
      {tab && (
        <Tabs value={tab} onValueChange={(next) => table.replaceAll({ tab: next })}>
          <TabsList>
            {visible.map((item) => (
              <TabsTrigger key={item.id} value={item.id}>
                {labels.settings.tabs[item.id]}
              </TabsTrigger>
            ))}
          </TabsList>
          <TabsContent value="company" className="mt-4">
            {tab === "company" && <CompanyTab />}
          </TabsContent>
          <TabsContent value="users" className="mt-4">
            {tab === "users" && <UsersTab />}
          </TabsContent>
          <TabsContent value="roles" className="mt-4">
            {tab === "roles" && <RolesTab />}
          </TabsContent>
          <TabsContent value="audit" className="mt-4">
            {tab === "audit" && <AuditTab />}
          </TabsContent>
        </Tabs>
      )}
    </>
  );
}
