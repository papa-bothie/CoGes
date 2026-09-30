"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useCompanyLocale } from "@/hooks/use-me";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { queryKeys } from "@/lib/api/queries/keys";
import { compareDecimal, parseDecimalInput, subtractDecimal } from "@/lib/decimal";
import { formatQty } from "@/lib/format";
import { labels } from "@/lib/labels";

/**
 * Premier temps d'un retour : les lignes et les quantités rendues. Le montant
 * remboursable n'est **pas** estimé ici — il est calculé par le serveur à
 * l'enregistrement, et montré sur l'écran du retour, où se fait le règlement.
 */
export function ReturnForm({ saleId }: { saleId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { currency } = useCompanyLocale();
  const idempotency = useIdempotencyKey();
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [lineErrors, setLineErrors] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const sale = useQuery({
    queryKey: queryKeys.sales.detail(saleId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/sales/{sale_id}", { params: { path: { sale_id: saleId } } })),
  });

  const create = useMutation({
    meta: { toastError: false },
    mutationFn: (lines: { sale_item_id: string; qty: string }[]) =>
      unwrap(
        api.POST("/api/v1/sales/{sale_id}/returns", {
          params: { path: { sale_id: saleId } },
          body: { lines, reason: reason.trim() || null },
          headers: idempotency.headers,
        }),
      ),
    onSuccess: (created) => {
      idempotency.renew();
      queryClient.setQueryData(queryKeys.saleReturns.detail(created.id), created);
      for (const key of [
        queryKeys.sales.all,
        queryKeys.stock.all,
        queryKeys.dashboard,
        queryKeys.saleReturns.all,
      ]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      toast.success(labels.returns.created(created.return_no));
      router.push(`/sales/returns/${created.id}`);
    },
    onError: (error) => setFormError(errorMessage(error)),
  });

  if (sale.isError) return <ErrorState error={sale.error} onRetry={() => void sale.refetch()} />;
  if (!sale.data) return <Skeleton className="h-96 w-full" />;

  const data = sale.data;
  const rows = data.items.map((item) => ({
    item,
    returnable: subtractDecimal(item.qty, item.returned_qty) ?? "0",
  }));
  const anyReturnable = rows.some(({ returnable }) => compareDecimal(returnable, "0") === 1);

  const submit = () => {
    const errors: Record<string, string> = {};
    const lines: { sale_item_id: string; qty: string }[] = [];
    for (const { item, returnable } of rows) {
      const raw = quantities[item.id]?.trim();
      if (!raw) continue;
      const qty = parseDecimalInput(raw);
      if (qty === null) errors[item.id] = labels.sales.invalidNumber;
      else if (compareDecimal(qty, returnable) === 1) {
        errors[item.id] = labels.returns.exceeds(formatQty(returnable));
      } else if (compareDecimal(qty, "0") === 1) lines.push({ sale_item_id: item.id, qty });
    }
    setLineErrors(errors);
    if (Object.keys(errors).length > 0) return;
    if (lines.length === 0) {
      setFormError(labels.returns.nothingSelected);
      return;
    }
    setFormError(null);
    create.mutate(lines);
  };

  return (
    <>
      <Link
        href={`/sales/${saleId}`}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {labels.receipt.back}
      </Link>
      <PageHeader title={labels.returns.newTitle(data.sale_no)} />

      {!anyReturnable ? (
        <EmptyState title={labels.returns.nothingReturnable} />
      ) : (
        <form
          className="space-y-6"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <Card>
            <CardHeader>
              <CardTitle>{labels.sales.lines}</CardTitle>
              <CardDescription>{labels.returns.intro}</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="px-4">{labels.sales.lineColumns.product}</TableHead>
                      <TableHead className="px-4 text-right">
                        {labels.sales.lineColumns.total}
                      </TableHead>
                      <TableHead className="px-4 text-right">{labels.returns.sold}</TableHead>
                      <TableHead className="px-4 text-right">
                        {labels.returns.alreadyReturned}
                      </TableHead>
                      <TableHead className="px-4 text-right">{labels.returns.returnable}</TableHead>
                      <TableHead className="px-4 text-right">{labels.returns.toReturn}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map(({ item, returnable }) => {
                      const name = item.product_name ?? labels.sales.deletedProduct;
                      const exhausted = compareDecimal(returnable, "0") !== 1;
                      const error = lineErrors[item.id];
                      return (
                        <TableRow key={item.id}>
                          <TableCell className="px-4">
                            <p className="font-medium">{name}</p>
                            <p className="text-xs numeric text-muted-foreground">{item.sku}</p>
                          </TableCell>
                          <TableCell className="px-4 text-right">
                            <Money value={item.line_total} currency={currency} />
                          </TableCell>
                          <TableCell className="px-4 text-right numeric">
                            {formatQty(item.qty)}
                          </TableCell>
                          <TableCell className="px-4 text-right numeric">
                            {formatQty(item.returned_qty)}
                          </TableCell>
                          <TableCell className="px-4 text-right font-medium numeric">
                            {formatQty(returnable)}
                          </TableCell>
                          <TableCell className="px-4">
                            <div className="ml-auto w-24 space-y-1">
                              <Input
                                inputMode="decimal"
                                aria-label={labels.returns.qtyLabel(name)}
                                aria-invalid={Boolean(error)}
                                placeholder="0"
                                disabled={exhausted || create.isPending}
                                value={quantities[item.id] ?? ""}
                                onChange={(event) =>
                                  setQuantities((current) => ({
                                    ...current,
                                    [item.id]: event.target.value,
                                  }))
                                }
                                className="h-8 text-right numeric"
                              />
                              <FieldError message={error} />
                            </div>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="space-y-1.5">
              <Label htmlFor="return-reason">{labels.returns.reason}</Label>
              <Textarea
                id="return-reason"
                value={reason}
                maxLength={500}
                onChange={(event) => setReason(event.target.value)}
              />
            </CardContent>
          </Card>

          <div className="flex flex-wrap items-center justify-end gap-3">
            <FieldError message={formError} />
            <Button type="submit" disabled={create.isPending}>
              {create.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {labels.returns.submit}
            </Button>
          </div>
        </form>
      )}
    </>
  );
}
