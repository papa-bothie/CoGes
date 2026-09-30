"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { FolderTree, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo } from "react";

import { DataTable, type Column } from "@/components/data-table";
import { ErrorState } from "@/components/error-state";
import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { StockStatusBadge } from "@/components/status/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { flattenTree, useCategories } from "@/lib/api/queries/categories";
import { queryKeys } from "@/lib/api/queries/keys";
import { useStockFor } from "@/lib/api/queries/stock";
import type { Schemas } from "@/lib/api/schema";
import { formatQtyWithUnit } from "@/lib/format";
import { labels } from "@/lib/labels";

type Product = Schemas["ProductRead"];
const ALL = "all";

/**
 * Catalogue (`/products` : recherche, catégorie, état, prix) complété par le stock des
 * articles de la page (`/inventory/stock?product_id=…`, ADR 0012 et 0050).
 */
export function ProductsListView() {
  const router = useRouter();
  const table = useTableParams();
  const { currency } = useCompanyLocale();
  const categories = useCategories();
  const tree = useMemo(() => flattenTree(categories.data ?? []), [categories.data]);
  const categoryPath = useMemo(() => new Map(tree.map((node) => [node.id, node.path])), [tree]);

  const categoryId = table.get("category");
  // Par défaut, le catalogue actif : c'est lui qu'on vend.
  const state = table.get("state") ?? "active";
  const params = {
    page: table.page,
    page_size: table.pageSize,
    search: table.search || undefined,
    category_id: categoryId ?? undefined,
    is_active: state === "all" ? undefined : state === "active",
  };
  const query = useQuery({
    queryKey: queryKeys.products.list(params),
    queryFn: () => unwrap(api.GET("/api/v1/products", { params: { query: params } })),
    placeholderData: keepPreviousData,
  });
  const ids = useMemo(() => (query.data?.items ?? []).map((product) => product.id), [query.data]);
  const stock = useStockFor(ids);

  const columns: Column<Product>[] = [
    {
      id: "product",
      header: labels.products.columns.product,
      cell: (product) => (
        <div>
          <p className="font-medium">{product.name}</p>
          <p className="text-xs numeric text-muted-foreground">{product.sku}</p>
        </div>
      ),
    },
    {
      id: "category",
      header: labels.products.columns.category,
      cell: (product) =>
        (product.category_id && categoryPath.get(product.category_id)) ?? (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      id: "price",
      header: labels.products.columns.price,
      numeric: true,
      cell: (product) =>
        product.unit_price ? (
          <Money value={product.unit_price} currency={currency} className="font-medium" />
        ) : (
          <span className="text-muted-foreground">{labels.products.noPrice}</span>
        ),
    },
    {
      id: "stock",
      header: labels.products.columns.stock,
      numeric: true,
      cell: (product) => {
        if (!product.is_stock_tracked) {
          return <span className="text-muted-foreground">{labels.products.notTracked}</span>;
        }
        const line = stock.data?.get(product.id);
        return line ? (
          <span className="whitespace-nowrap">
            {formatQtyWithUnit(
              line.qty_on_hand,
              labels.units[product.unit],
              labels.unitsPlural[product.unit],
            )}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        );
      },
    },
    {
      id: "status",
      header: labels.products.columns.status,
      cell: (product) => {
        const line = stock.data?.get(product.id);
        return (
          <span className="flex flex-wrap gap-1">
            {!product.is_active && <Badge variant="neutral">{labels.products.inactiveBadge}</Badge>}
            {product.is_stock_tracked && line && <StockStatusBadge status={line.status} />}
            {product.is_stock_tracked && !line && (
              <Badge variant="neutral">{labels.products.noMovement}</Badge>
            )}
          </span>
        );
      },
    },
  ];

  return (
    <>
      <PageHeader
        title={labels.nav.products}
        count={query.data ? labels.products.count(query.data.total) : undefined}
        actions={
          <>
            <Button variant="outline" asChild>
              <Link href="/products/categories">
                <FolderTree aria-hidden />
                {labels.products.categories}
              </Link>
            </Button>
            <Can permission="products:create">
              <Button asChild>
                <Link href="/products/new">
                  <Plus aria-hidden />
                  {labels.products.add}
                </Link>
              </Button>
            </Can>
          </>
        }
      />
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={labels.nav.products}
          columns={columns}
          rows={query.data?.items}
          rowKey={(product) => product.id}
          total={query.data?.total ?? 0}
          page={table.page}
          pageSize={table.pageSize}
          onPageChange={table.setPage}
          loading={query.isFetching}
          onRowClick={(product) => router.push(`/products/${product.id}`)}
          empty={labels.products.empty}
          search={{
            value: table.search,
            onChange: table.setSearch,
            placeholder: labels.products.searchPlaceholder,
          }}
          filters={
            <>
              <Select
                value={categoryId ?? ALL}
                onValueChange={(value) => table.setFilter("category", value === ALL ? null : value)}
              >
                <SelectTrigger className="w-56" aria-label={labels.products.categoryFilter}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>{labels.products.allCategories}</SelectItem>
                  {tree.map((node) => (
                    <SelectItem key={node.id} value={node.id}>
                      <span style={{ paddingLeft: `${node.depth * 12}px` }}>{node.name}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={state}
                onValueChange={(value) =>
                  table.setFilter("state", value === "active" ? null : value)
                }
              >
                <SelectTrigger className="w-36" aria-label={labels.products.activeFilter}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="active">{labels.products.active}</SelectItem>
                  <SelectItem value="inactive">{labels.products.inactive}</SelectItem>
                  <SelectItem value="all">{labels.products.all}</SelectItem>
                </SelectContent>
              </Select>
            </>
          }
        />
      )}
    </>
  );
}
