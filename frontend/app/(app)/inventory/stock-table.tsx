"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { DataTable, type Column } from "@/components/data-table";
import { ErrorState } from "@/components/error-state";
import { Money } from "@/components/money";
import { StockStatusBadge } from "@/components/status/status-badge";
import { useCompanyLocale } from "@/hooks/use-me";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { StockLine } from "@/lib/api/queries/stock";
import { formatDateTime, formatQty } from "@/lib/format";
import { labels } from "@/lib/labels";

const HIGHLIGHT = {
  ok: undefined,
  low: "bg-warning/5 hover:bg-warning/10",
  out: "bg-destructive/5 hover:bg-destructive/10",
} as const;

/** Stock valorisé au CMP, ruptures et seuils bas en tête (ordre de l'API), surlignés. */
export function StockTable({ onTotal }: { onTotal: (total: number) => void }) {
  const router = useRouter();
  const table = useTableParams();
  const { timeZone, currency } = useCompanyLocale();
  const params = { page: table.page, page_size: table.pageSize };
  const query = useQuery({
    queryKey: queryKeys.stock.list(params),
    queryFn: () => unwrap(api.GET("/api/v1/inventory/stock", { params: { query: params } })),
    placeholderData: keepPreviousData,
  });

  const total = query.data?.total;
  useEffect(() => {
    if (total !== undefined) onTotal(total);
  }, [total, onTotal]);

  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;

  const columns: Column<StockLine>[] = [
    {
      id: "product",
      header: labels.stock.columns.product,
      cell: (line) => (
        <div>
          <p className="font-medium">{line.name}</p>
          <p className="text-xs numeric text-muted-foreground">{line.sku}</p>
        </div>
      ),
    },
    {
      id: "category",
      secondary: true,
      header: labels.stock.columns.category,
      cell: (line) => line.category_name ?? <span className="text-muted-foreground">—</span>,
    },
    {
      id: "qty",
      header: labels.stock.columns.qty,
      numeric: true,
      cell: (line) => <span className="font-medium">{formatQty(line.qty_on_hand)}</span>,
    },
    {
      id: "reorder",
      header: labels.stock.columns.reorderPoint,
      numeric: true,
      cell: (line) => formatQty(line.reorder_point),
    },
    {
      id: "avgCost",
      header: labels.stock.columns.avgCost,
      numeric: true,
      cell: (line) => <Money value={line.avg_cost} currency={currency} />,
    },
    {
      id: "value",
      header: labels.stock.columns.value,
      numeric: true,
      cell: (line) => (
        <Money value={line.stock_value} currency={currency} className="font-medium" />
      ),
    },
    {
      id: "last",
      secondary: true,
      header: labels.stock.columns.lastMovement,
      cell: (line) => (
        <span className="numeric whitespace-nowrap">
          {formatDateTime(line.last_movement_at, timeZone)}
        </span>
      ),
    },
    {
      id: "status",
      header: labels.stock.columns.status,
      cell: (line) => <StockStatusBadge status={line.status} />,
    },
  ];

  return (
    <div className="space-y-2">
      <p className="text-sm text-muted-foreground">{labels.stock.orderHint}</p>
      <DataTable
        caption={labels.stock.tabs.current}
        columns={columns}
        rows={query.data?.items}
        rowKey={(line) => line.product_id}
        total={query.data?.total ?? 0}
        page={table.page}
        pageSize={table.pageSize}
        onPageChange={table.setPage}
        loading={query.isFetching}
        rowClassName={(line) => HIGHLIGHT[line.status]}
        onRowClick={(line) => router.push(`/products/${line.product_id}`)}
        empty={labels.stock.empty}
      />
    </div>
  );
}
