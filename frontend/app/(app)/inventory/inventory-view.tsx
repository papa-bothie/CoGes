"use client";

import { ArrowLeft, Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { MovementDialog } from "@/components/inventory/movement-dialog";
import { Button } from "@/components/ui/button";
import { Can } from "@/hooks/use-permission";
import { labels } from "@/lib/labels";

import { MovementJournal } from "./movement-journal";

/**
 * « Tous les mouvements » : le journal de tous les articles, gardé derrière un lien de
 * l'écran Stock (ADR 0071). On y annule un mouvement manuel (ADR 0017) et on y saisit les
 * mouvements rares (renvoi au fournisseur, stock de départ) ; la correction et la
 * livraison ont leurs écrans.
 */
export function InventoryView() {
  const [adding, setAdding] = useState(false);
  const t = labels.stockScreens.list;

  return (
    <div className="mx-auto flex max-w-page flex-col gap-5">
      <Link
        href="/products"
        className="inline-flex min-h-11 items-center gap-2 self-start font-bold text-ventes hover:text-ventes-encre pointer-coarse:min-h-12"
      >
        <ArrowLeft className="size-[22px]" aria-hidden />
        {t.title}
      </Link>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{t.journal}</h1>
        <Can permission="inventory:create">
          <Button variant="secondaire" size="standard" onClick={() => setAdding(true)}>
            <Plus aria-hidden />
            {labels.stock.newMovement}
          </Button>
        </Can>
      </div>
      <MovementJournal />
      <MovementDialog open={adding} onOpenChange={setAdding} defaultType="supplier_return_out" />
    </div>
  );
}
