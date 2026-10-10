"use client";

import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { labels } from "@/lib/labels";

import {
  PersonForm,
  type Customer,
  type PersonKind,
  type SavedPerson,
  type Supplier,
} from "./person-form";

export type { PersonKind } from "./person-form";

/**
 * « Ajouter une personne » dans une fenêtre : seulement là où quitter l'écran perdrait le
 * travail en cours (le choix du client d'une vente, le fournisseur d'une livraison). Les
 * listes et les fiches ouvrent la page (maquette 15, ADR 0072).
 */
export function PersonFormDialog({
  open,
  onOpenChange,
  kind,
  initialKind = "customer",
  person,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  kind?: PersonKind;
  initialKind?: PersonKind;
  person?: Customer | Supplier;
  onSaved?: (saved: SavedPerson) => void;
}) {
  const t = labels.people;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{person ? t.editTitle[kind ?? initialKind] : t.addTitle}</DialogTitle>
        </DialogHeader>
        {open && (
          <PersonForm
            kind={kind}
            initialKind={initialKind}
            person={person}
            onSaved={(saved) => {
              if (!person) toast.success(t.created[saved.kind]);
              onOpenChange(false);
              onSaved?.(saved);
            }}
            actions={
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                {labels.common.close}
              </Button>
            }
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
