"use client";

import { Plus } from "lucide-react";
import { useState } from "react";

import { MovementDialog } from "@/components/inventory/movement-dialog";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Can } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { labels } from "@/lib/labels";

import { MovementJournal } from "./movement-journal";
import { StockTable } from "./stock-table";

type Tab = "current" | "journal";

/** Stock courant valorisé au CMP, et journal des mouvements (onglet gardé dans l'URL). */
export function InventoryView() {
  const table = useTableParams();
  const tab: Tab = table.get("tab") === "journal" ? "journal" : "current";
  const [dialogOpen, setDialogOpen] = useState(false);
  const [total, setTotal] = useState<number | null>(null);

  return (
    <>
      <PageHeader
        title={labels.nav.inventory}
        count={total === null ? undefined : labels.stock.count(total)}
        actions={
          <Can permission="inventory:create">
            <Button onClick={() => setDialogOpen(true)}>
              <Plus aria-hidden />
              {labels.stock.newMovement}
            </Button>
          </Can>
        }
      />
      <Tabs
        value={tab}
        onValueChange={(value) =>
          // Changer d'onglet repart d'une liste vierge : les filtres ne sont pas partagés.
          table.replaceAll(value === "journal" ? { tab: "journal" } : {})
        }
      >
        <TabsList>
          <TabsTrigger value="current">{labels.stock.tabs.current}</TabsTrigger>
          <TabsTrigger value="journal">{labels.stock.tabs.journal}</TabsTrigger>
        </TabsList>
        <TabsContent value="current" className="mt-4">
          {tab === "current" && <StockTable onTotal={setTotal} />}
        </TabsContent>
        <TabsContent value="journal" className="mt-4">
          {tab === "journal" && <MovementJournal />}
        </TabsContent>
      </Tabs>
      <MovementDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </>
  );
}
