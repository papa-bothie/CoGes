"use client";

import { ClipboardCheck, PackagePlus, Truck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { MovementDialog } from "@/components/inventory/movement-dialog";
import { StockCorrectionDialog } from "@/components/inventory/stock-correction-dialog";
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
  const [receiving, setReceiving] = useState(false);
  const [correcting, setCorrecting] = useState(false);
  const [total, setTotal] = useState<number | null>(null);

  return (
    <>
      <PageHeader
        title={labels.nav.inventory}
        count={total === null ? undefined : labels.stock.count(total)}
        actions={
          <Can permission="inventory:create">
            <div className="flex flex-wrap gap-2.5">
              <Can permission="products:create">
                <Button variant="secondaire" asChild>
                  <Link href="/products/new">
                    <PackagePlus aria-hidden />
                    {labels.stock.newProduct}
                  </Link>
                </Button>
              </Can>
              <Button variant="secondaire" onClick={() => setReceiving(true)}>
                <Truck aria-hidden />
                {labels.stock.receive}
              </Button>
              <Button variant="stock" onClick={() => setCorrecting(true)}>
                <ClipboardCheck aria-hidden />
                {labels.stock.correction.open}
              </Button>
            </div>
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
      <MovementDialog open={receiving} onOpenChange={setReceiving} defaultType="purchase_in" />
      <StockCorrectionDialog open={correcting} onOpenChange={setCorrecting} />
    </>
  );
}
