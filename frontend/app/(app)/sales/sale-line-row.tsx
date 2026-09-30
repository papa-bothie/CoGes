"use client";

import { Trash2 } from "lucide-react";
import { useState, type KeyboardEvent } from "react";

import { FieldError } from "@/components/field-error";
import { Money } from "@/components/money";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TableCell, TableRow } from "@/components/ui/table";
import type { StockLine } from "@/lib/api/queries/stock";
import type { Schemas } from "@/lib/api/schema";
import { parseDecimalInput, toInputDecimal } from "@/lib/decimal";
import { formatQty } from "@/lib/format";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

type SaleItem = Schemas["SaleItemRead"];

export type LineChange = { qty?: string; discount?: string };

/**
 * Ligne d'un brouillon. Quantité et remise sont envoyées au serveur **à la sortie du
 * champ** (ou sur Entrée) ; les montants affichés sont ceux qu'il renvoie.
 */
export function SaleLineRow({
  item,
  currency,
  showTax,
  stock,
  short,
  error,
  disabled,
  onChange,
  onRemove,
}: {
  item: SaleItem;
  currency: string;
  showTax: boolean;
  stock: StockLine | undefined;
  short: boolean;
  error: string | undefined;
  disabled: boolean;
  onChange: (change: LineChange) => void;
  onRemove: () => void;
}) {
  const name = item.product_name ?? labels.sales.deletedProduct;
  const [qty, setQty] = useState(toInputDecimal(item.qty));
  const [discount, setDiscount] = useState(toInputDecimal(item.discount));
  const [invalid, setInvalid] = useState<string | null>(null);

  // Le serveur fait foi : une valeur renvoyée (rejeu, autre onglet) remplace la saisie.
  const [server, setServer] = useState({ qty: item.qty, discount: item.discount });
  if (server.qty !== item.qty || server.discount !== item.discount) {
    setServer({ qty: item.qty, discount: item.discount });
    setQty(toInputDecimal(item.qty));
    setDiscount(toInputDecimal(item.discount));
  }

  const commit = () => {
    const nextQty = parseDecimalInput(qty);
    const nextDiscount = parseDecimalInput(discount || "0");
    if (nextQty === null || nextDiscount === null) {
      setInvalid(labels.sales.invalidNumber);
      return;
    }
    setInvalid(null);
    const change: LineChange = {};
    if (nextQty !== toInputDecimal(item.qty).replace(",", ".")) change.qty = nextQty;
    if (nextDiscount !== toInputDecimal(item.discount).replace(",", ".")) {
      change.discount = nextDiscount;
    }
    if (change.qty !== undefined || change.discount !== undefined) onChange(change);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") event.currentTarget.blur();
  };

  const message = invalid ?? error;
  const errorId = `line-error-${item.id}`;

  return (
    <>
      <TableRow className={cn(message && "border-b-0")} data-testid="sale-line">
        <TableCell className="px-3">
          <p className="font-medium">{name}</p>
          <p className="text-xs numeric text-muted-foreground">{item.sku}</p>
        </TableCell>
        <TableCell className="px-3 text-right">
          <Money value={item.unit_price} currency={currency} />
        </TableCell>
        <TableCell className="px-3">
          <Input
            inputMode="decimal"
            aria-label={labels.sales.qtyLabel(name)}
            aria-invalid={Boolean(message) || short}
            aria-describedby={message ? errorId : `stock-${item.id}`}
            value={qty}
            disabled={disabled}
            onChange={(event) => setQty(event.target.value)}
            onBlur={commit}
            onKeyDown={onKeyDown}
            className="ml-auto h-8 w-16 text-right numeric"
          />
          <p
            id={`stock-${item.id}`}
            className={cn(
              "mt-1 text-right text-xs numeric whitespace-nowrap",
              short ? "font-medium text-destructive" : "text-muted-foreground",
            )}
          >
            {stock
              ? labels.sales.availableShort(formatQty(stock.qty_on_hand))
              : labels.sales.notStocked}
          </p>
        </TableCell>
        <TableCell className="px-3">
          <Input
            inputMode="decimal"
            aria-label={labels.sales.discountLabel(name)}
            value={discount}
            disabled={disabled}
            onChange={(event) => setDiscount(event.target.value)}
            onBlur={commit}
            onKeyDown={onKeyDown}
            className="ml-auto h-8 w-20 text-right numeric"
          />
        </TableCell>
        {showTax && (
          <TableCell className="px-3 text-right">
            <Money value={item.tax_amount} currency={currency} />
          </TableCell>
        )}
        <TableCell className="px-3 text-right">
          <Money value={item.line_total} currency={currency} className="font-medium" />
        </TableCell>
        <TableCell className="w-10 px-2">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={labels.sales.removeLine(name)}
            disabled={disabled}
            onClick={onRemove}
          >
            <Trash2 />
          </Button>
        </TableCell>
      </TableRow>
      {message && (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={showTax ? 7 : 6} className="px-3 pt-0 pb-2">
            <FieldError id={errorId} message={message} />
          </TableCell>
        </TableRow>
      )}
    </>
  );
}
