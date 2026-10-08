"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { DataTable, type Column } from "@/components/data-table";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Can } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { labels } from "@/lib/labels";

import { PersonFormDialog } from "@/components/people/person-form-dialog";

type Supplier = Schemas["SupplierRead"];

export function SuppliersListView() {
  const router = useRouter();
  const table = useTableParams();
  const [creating, setCreating] = useState(false);
  const params = {
    page: table.page,
    page_size: table.pageSize,
    search: table.search || undefined,
  };
  const query = useQuery({
    queryKey: queryKeys.suppliers.list(params),
    queryFn: () => unwrap(api.GET("/api/v1/suppliers", { params: { query: params } })),
    placeholderData: keepPreviousData,
  });

  const columns: Column<Supplier>[] = [
    {
      id: "name",
      header: labels.suppliers.columns.name,
      cell: (supplier) => <span className="font-medium">{supplier.name}</span>,
    },
    {
      id: "phone",
      header: labels.suppliers.columns.phone,
      cell: (supplier) => <span className="numeric">{supplier.phone ?? "—"}</span>,
    },
  ];

  return (
    <>
      <PageHeader
        title={labels.nav.suppliers}
        count={query.data ? labels.suppliers.count(query.data.total) : undefined}
        actions={
          <Can permission="suppliers:create">
            <Button onClick={() => setCreating(true)}>
              <Plus aria-hidden />
              {labels.people.add}
            </Button>
          </Can>
        }
      />
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={labels.nav.suppliers}
          columns={columns}
          rows={query.data?.items}
          rowKey={(supplier) => supplier.id}
          total={query.data?.total ?? 0}
          page={table.page}
          pageSize={table.pageSize}
          onPageChange={table.setPage}
          loading={query.isFetching}
          onRowClick={(supplier) => router.push(`/suppliers/${supplier.id}`)}
          empty={labels.suppliers.empty}
          search={{
            value: table.search,
            onChange: table.setSearch,
            placeholder: labels.suppliers.searchPlaceholder,
          }}
        />
      )}
      <PersonFormDialog
        open={creating}
        onOpenChange={setCreating}
        initialKind="supplier"
        onSaved={(saved) =>
          router.push(
            `/${saved.kind === "customer" ? "customers" : "suppliers"}/${saved.person.id}`,
          )
        }
      />
    </>
  );
}
