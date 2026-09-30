"use client";

import { PageHeader } from "@/components/page-header";
import { PeriodPicker } from "@/components/period/period-picker";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMe } from "@/hooks/use-me";
import { useTableParams } from "@/hooks/use-table-params";
import { labels } from "@/lib/labels";
import { can, type PermissionCode } from "@/lib/permissions";

import { DebtsTab } from "./debts-tab";
import { ExpensesTab } from "./expenses-tab";
import { OverviewTab } from "./overview-tab";
import { PaymentsTab } from "./payments-tab";

const TABS = [
  { id: "overview", permission: "analytics:read" },
  { id: "payments", permission: "payments:read" },
  { id: "debts", permission: "debts:read" },
  { id: "expenses", permission: "expenses:read" },
] as const satisfies readonly { id: string; permission: PermissionCode }[];

type Tab = (typeof TABS)[number]["id"];

/**
 * Finance de gestion : vue d'ensemble, paiements, dettes, dépenses. L'onglet et la période
 * vivent dans l'URL ; chaque onglet n'apparaît qu'avec son droit de lecture (le serveur
 * revérifie). Tous les montants viennent de l'API.
 */
export function FinanceView() {
  const table = useTableParams();
  const { data: me } = useMe();
  const visible = TABS.filter((tab) => can(me?.permissions, tab.permission));
  const requested = table.get("tab");
  const tab: Tab | undefined = visible.find((item) => item.id === requested)?.id ?? visible[0]?.id;

  const switchTab = (next: string) => {
    // La période suit d'un onglet à l'autre ; filtres et pagination repartent à zéro.
    const keep: Record<string, string> = { tab: next };
    for (const key of ["period", "from", "to"]) {
      const value = table.get(key);
      if (value) keep[key] = value;
    }
    table.replaceAll(keep);
  };

  return (
    <>
      <PageHeader
        title={labels.nav.finance}
        // Les dettes sont un état à l'instant, pas un flux : aucune période ne s'y applique.
        actions={tab && tab !== "debts" ? <PeriodPicker /> : undefined}
      />
      {tab && (
        <Tabs value={tab} onValueChange={switchTab}>
          <TabsList>
            {visible.map((item) => (
              <TabsTrigger key={item.id} value={item.id}>
                {labels.finance.tabs[item.id]}
              </TabsTrigger>
            ))}
          </TabsList>
          <TabsContent value="overview" className="mt-4 space-y-4">
            {tab === "overview" && <OverviewTab />}
          </TabsContent>
          <TabsContent value="payments" className="mt-4">
            {tab === "payments" && <PaymentsTab />}
          </TabsContent>
          <TabsContent value="debts" className="mt-4">
            {tab === "debts" && <DebtsTab />}
          </TabsContent>
          <TabsContent value="expenses" className="mt-4">
            {tab === "expenses" && <ExpensesTab />}
          </TabsContent>
        </Tabs>
      )}
    </>
  );
}
