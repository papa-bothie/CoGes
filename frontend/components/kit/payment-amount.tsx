"use client";

import type { ReactNode } from "react";

import type { Check, Shortcut } from "@/lib/payment-amount";
import { cn } from "@/lib/utils";

import { AmountField, AmountShortcuts, NumericPad } from "./amount-field";
import { RUBRIQUE_CLASSES, type Rubrique } from "./rubrique";

/**
 * Montant tapé librement (lot 1) : le champ, les raccourcis, le pavé numérique pour les
 * tablettes sans clavier, et la phrase qui dit tout de suite si le montant va
 * (« Il restera 4 000 F à payer »). Le bouton de l'écran reste grisé tant que `check.ok`
 * est faux.
 */
export function PaymentAmount({
  label,
  value,
  onChange,
  shortcuts,
  check,
  rubrique = "ventes",
  id,
  autoFocus,
  placeholder,
  okRubrique,
}: {
  label: ReactNode;
  value: string;
  onChange: (value: string) => void;
  shortcuts: readonly Shortcut[];
  check: Check;
  rubrique?: Rubrique;
  id?: string;
  autoFocus?: boolean;
  placeholder?: string;
  /** Couleur du message quand le montant va (vente en partie : orange, il restera à payer). */
  okRubrique?: Rubrique;
}) {
  return (
    <div className="space-y-3">
      <AmountField
        id={id}
        label={label}
        value={value}
        onChange={onChange}
        rubrique={rubrique}
        autoFocus={autoFocus}
        placeholder={placeholder}
        invalid={check.tone === "trop"}
      />
      {shortcuts.length > 0 && <AmountShortcuts shortcuts={shortcuts} onPick={onChange} />}
      <NumericPad value={value} onChange={onChange} rubrique={rubrique} />
      {/* Sous le pavé, comme la maquette : la phrase change à chaque chiffre. */}
      <p
        role="status"
        className={cn(
          "rounded-champ px-4 py-3 text-corps font-bold",
          check.tone === "trop"
            ? "bg-stock-teinte text-stock-encre"
            : check.tone === "bon"
              ? cn(
                  RUBRIQUE_CLASSES[okRubrique ?? rubrique].tint,
                  RUBRIQUE_CLASSES[okRubrique ?? rubrique].ink,
                )
              : "bg-muted text-foreground",
        )}
      >
        {check.message}
      </p>
    </div>
  );
}
