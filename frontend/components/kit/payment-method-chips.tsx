"use client";

import { useId, useState } from "react";

import type { Schemas } from "@/lib/api/schema";
import { labels } from "@/lib/labels";

import { Chip } from "./chip";
import type { Rubrique } from "./rubrique";

type Method = Schemas["PaymentMethod"];

/** Les trois moyens de la maquette v2, en grosses puces. */
export const MAIN_METHODS: readonly Method[] = ["cash", "wave", "orange_money"];
/** Les autres, derrière « Autre moyen » : rares chez un commerçant, jamais supprimés. */
export const OTHER_METHODS: readonly Method[] = ["bank_transfer", "card", "cheque"];

/**
 * « Comment ? » : Espèces, Wave, Orange Money en puces pleines de la rubrique (ADR 0068).
 * Virement, carte et chèque restent accessibles derrière « Autre moyen ».
 */
export function PaymentMethodChips({
  value,
  onChange,
  rubrique = "ventes",
  label = labels.payment.how,
  hideLabel = false,
  stretch = false,
  tone = "plein",
}: {
  value: Method;
  onChange: (value: Method) => void;
  rubrique?: Rubrique;
  label?: string;
  /** Libellé lu seulement par les lecteurs d'écran (maquette 02 : les puces seules). */
  hideLabel?: boolean;
  /** Puces étirées sur la ligne, comme dans le ticket de vente. */
  stretch?: boolean;
  /** `teinte` : la puce choisie prend la teinte claire (maquette 02), pas la couleur pleine. */
  tone?: "plein" | "teinte";
}) {
  const labelId = useId();
  const [more, setMore] = useState(OTHER_METHODS.includes(value));
  const shown = more ? [...MAIN_METHODS, ...OTHER_METHODS] : MAIN_METHODS;
  return (
    <div className="space-y-2">
      <p id={labelId} className={hideLabel ? "sr-only" : "text-libelle"}>
        {label}
      </p>
      <div role="group" aria-labelledby={labelId} className="flex flex-wrap gap-2.5">
        {shown.map((method) => (
          <Chip
            key={method}
            rubrique={rubrique}
            tone={tone}
            selected={value === method}
            onClick={() => onChange(method)}
            className={stretch ? "flex-[1_1_110px]" : undefined}
          >
            {labels.paymentMethods[method]}
          </Chip>
        ))}
        {!more && (
          <Chip
            rubrique={rubrique}
            onClick={() => setMore(true)}
            className={stretch ? "flex-[1_1_110px]" : undefined}
          >
            {labels.payment.otherMethods}
          </Chip>
        )}
      </div>
    </div>
  );
}
