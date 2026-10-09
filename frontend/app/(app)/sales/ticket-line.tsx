"use client";

import { useState } from "react";

import { cleanAmount } from "@/components/kit/amount-field";
import { cleanQuantity } from "@/components/kit/quantity-stepper";
import { fieldClasses } from "@/components/kit/rubrique";
import { FieldError } from "@/components/field-error";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal, parseDecimalInput, toInputDecimal } from "@/lib/decimal";
import { formatAmount, formatFigure } from "@/lib/format";
import { labels } from "@/lib/labels";
import { wholeUnits } from "@/lib/payment-amount";
import { cn } from "@/lib/utils";

type Item = Schemas["SaleItemRead"];
export type LineChange = { qty?: string; discount?: string };

const t = labels.sales.editor;

const STEP = cn(
  "flex size-12 shrink-0 items-center justify-center rounded-touche border-2 border-input bg-card text-[22px] font-bold text-foreground",
  "outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50",
);

/**
 * Une ligne du ticket (maquette 02) : nom et prix unitaire, − quantité +, total de la ligne,
 * puis « Faire une remise » qui ouvre un champ en francs (`discount` de la ligne). La
 * quantité se tape librement ; elle part au serveur quand on quitte le champ. Retirer le
 * dernier article enlève la ligne.
 */
export function TicketLine({
  item,
  currency,
  error,
  disabled,
  onChange,
  onRemove,
}: {
  item: Item;
  currency: string;
  error?: string;
  disabled: boolean;
  onChange: (change: LineChange) => void;
  onRemove: () => void;
}) {
  const name = item.product_name ?? labels.sales.deletedProduct;
  const discountValue = wholeUnits(item.discount).toString();
  const [qty, setQty] = useState(toInputDecimal(item.qty));
  const [discount, setDiscount] = useState(discountValue === "0" ? "" : discountValue);
  const [discountOpen, setDiscountOpen] = useState(discountValue !== "0");
  // Le serveur fait foi : sa réponse remplace ce qui a été tapé (état dérivé, recalé au
  // rendu plutôt que dans un effet).
  const [synced, setSynced] = useState({ qty: item.qty, discount: discountValue });
  if (synced.qty !== item.qty || synced.discount !== discountValue) {
    setSynced({ qty: item.qty, discount: discountValue });
    setQty(toInputDecimal(item.qty));
    setDiscount(discountValue === "0" ? "" : discountValue);
  }

  const commitQty = (raw: string) => {
    const parsed = parseDecimalInput(raw);
    if (parsed === null || compareDecimal(parsed, "0") !== 1) {
      if (parsed !== null) onRemove();
      else setQty(toInputDecimal(item.qty));
      return;
    }
    if (compareDecimal(parsed, item.qty) !== 0) onChange({ qty: parsed });
  };
  const step = (delta: 1 | -1) => {
    const current = parseDecimalInput(qty) ?? item.qty;
    const whole = wholeUnits(current) + BigInt(delta);
    if (whole <= 0n) onRemove();
    else onChange({ qty: whole.toString() });
  };
  const commitDiscount = () => {
    const value = discount || "0";
    if (value !== discountValue) onChange({ discount: value });
  };

  return (
    <div className="border-t border-filet">
      <div className="flex items-center gap-2.5 pt-3 pb-1">
        <div className="min-w-0 flex-1">
          <div className="font-bold">{name}</div>
          <div className="numeric text-muted-foreground">
            {t.unitPrice(formatAmount(item.unit_price, currency))}
          </div>
        </div>
        <button
          type="button"
          className={STEP}
          disabled={disabled}
          onClick={() => step(-1)}
          aria-label={t.decrease(name)}
        >
          <span aria-hidden>−</span>
        </button>
        <input
          inputMode="decimal"
          autoComplete="off"
          aria-label={labels.sales.qtyLabel(name)}
          aria-invalid={error ? true : undefined}
          value={qty}
          disabled={disabled}
          onChange={(event) => setQty(cleanQuantity(event.target.value))}
          onBlur={(event) => commitQty(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") commitQty(event.currentTarget.value);
          }}
          className={cn(
            fieldClasses("ventes"),
            "h-12 w-14 rounded-mini text-center text-[19px] font-extrabold numeric",
          )}
        />
        <button
          type="button"
          className={STEP}
          disabled={disabled}
          onClick={() => step(1)}
          aria-label={t.increase(name)}
        >
          <span aria-hidden>+</span>
        </button>
        <div className="w-[92px] text-right font-extrabold numeric">
          {formatFigure(item.line_total, currency)}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2.5 pb-2.5">
        <button
          type="button"
          onClick={() => setDiscountOpen((open) => !open)}
          aria-expanded={discountOpen}
          className="min-h-12 px-1 font-bold text-ventes-encre outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {discountValue !== "0"
            ? t.discountSet(formatAmount(item.discount, currency))
            : t.discountOpen}
        </button>
        {discountOpen && (
          <label className="flex items-center gap-2 font-semibold">
            {t.discount}
            <input
              inputMode="numeric"
              autoComplete="off"
              aria-label={t.discountAria(name)}
              value={discount}
              disabled={disabled}
              onChange={(event) => setDiscount(cleanAmount(event.target.value))}
              onBlur={commitDiscount}
              onKeyDown={(event) => {
                if (event.key === "Enter") commitDiscount();
              }}
              className={cn(
                fieldClasses("ventes"),
                "h-12 w-[110px] rounded-mini text-center text-[19px] font-extrabold numeric",
              )}
            />
            {labels.kit.currencyShort}
          </label>
        )}
      </div>
      <FieldError message={error} />
    </div>
  );
}
