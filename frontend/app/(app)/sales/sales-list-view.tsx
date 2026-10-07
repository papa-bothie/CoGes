"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { DataTable, type Column } from "@/components/data-table";
import { ErrorState } from "@/components/error-state";
import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { SalePaymentBadge, SaleStatusBadge } from "@/components/status/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCompanyLocale } from "@/hooks/use-me";
import { Can } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatDate } from "@/lib/format";
import { dayEndIso, dayStartIso } from "@/lib/format/zoned";
import { labels } from "@/lib/labels";

type Sale = Schemas["SaleRead"];
type SaleStatus = Schemas["SaleStatus"];

const STATUSES: readonly SaleStatus[] = ["draft", "confirmed", "cancelled"];
const ALL = "all";

export function SalesListView() {
  const router = useRouter();
  const table = useTableParams();
  const { timeZone, currency } = useCompanyLocale();

  const status = table.get("status") as SaleStatus | null;
  const from = table.get("from") ?? "";
  const to = table.get("to") ?? "";

  const params = {
    page: table.page,
    page_size: table.pageSize,
    status: status ?? undefined,
    search: table.search || undefined,
    date_from: (from && dayStartIso(from, timeZone)) || undefined,
    date_to: (to && dayEndIso(to, timeZone)) || undefined,
  };
  const query = useQuery({
    queryKey: queryKeys.sales.list(params),
    queryFn: () => unwrap(api.GET("/api/v1/sales", { params: { query: params } })),
    placeholderData: keepPreviousData,
  });

  const columns: Column<Sale>[] = [
    {
      id: "number",
      header: labels.sales.columns.number,
      cell: (sale) => <span className="font-medium numeric">{sale.sale_no}</span>,
    },
    {
      id: "customer",
      header: labels.sales.columns.customer,
      cell: (sale) =>
        sale.customer_name ?? (
          <span className="text-muted-foreground">{labels.sales.anonymous}</span>
        ),
    },
    {
      id: "date",
      header: labels.sales.columns.date,
      cell: (sale) => <span className="numeric">{formatDate(sale.sold_at, timeZone)}</span>,
    },
    {
      id: "total",
      header: labels.sales.columns.total,
      numeric: true,
      cell: (sale) => <Money value={sale.total} currency={currency} className="font-medium" />,
    },
    {
      id: "payment",
      header: labels.sales.columns.payment,
      cell: (sale) => <SalePaymentBadge sale={sale} currency={currency} />,
    },
    {
      id: "status",
      header: labels.sales.columns.status,
      cell: (sale) => <SaleStatusBadge status={sale.status} hasReturns={sale.has_returns} />,
    },
  ];

  return (
    <>
      <PageHeader
        title={labels.nav.sales}
        count={query.data ? labels.sales.count(query.data.total) : undefined}
        actions={
          <Can permission="sales:create">
            <Button asChild>
              <Link href="/sales/new">
                <Plus aria-hidden />
                {labels.sales.newSale}
              </Link>
            </Button>
          </Can>
        }
      />
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={labels.nav.sales}
          columns={columns}
          rows={query.data?.items}
          rowKey={(sale) => sale.id}
          total={query.data?.total ?? 0}
          page={table.page}
          pageSize={table.pageSize}
          onPageChange={table.setPage}
          loading={query.isFetching}
          onRowClick={(sale) =>
            router.push(sale.status === "draft" ? `/sales/${sale.id}/edit` : `/sales/${sale.id}`)
          }
          empty={labels.sales.empty}
          search={{
            value: table.search,
            onChange: table.setSearch,
            placeholder: labels.sales.searchPlaceholder,
          }}
          filters={
            <>
              <Select
                value={status ?? ALL}
                onValueChange={(value) => table.setFilter("status", value === ALL ? null : value)}
              >
                <SelectTrigger className="w-44" aria-label={labels.sales.statusFilter}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>{labels.sales.allStatuses}</SelectItem>
                  {STATUSES.map((value) => (
                    <SelectItem key={value} value={value}>
                      {labels.sales.status[value]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <label className="flex items-center gap-2 text-sm text-muted-foreground">
                {labels.sales.dateFrom}
                <Input
                  type="date"
                  value={from}
                  max={to || undefined}
                  onChange={(event) => table.setFilter("from", event.target.value || null)}
                  className="h-9 w-40"
                />
              </label>
              <label className="flex items-center gap-2 text-sm text-muted-foreground">
                {labels.sales.dateTo}
                <Input
                  type="date"
                  value={to}
                  min={from || undefined}
                  onChange={(event) => table.setFilter("to", event.target.value || null)}
                  className="h-9 w-40"
                />
              </label>
            </>
          }
        />
      )}
    </>
  );
}
