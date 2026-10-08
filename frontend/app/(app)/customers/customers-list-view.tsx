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

type Customer = Schemas["CustomerRead"];

export function CustomersListView() {
  const router = useRouter();
  const table = useTableParams();
  const [creating, setCreating] = useState(false);
  const params = {
    page: table.page,
    page_size: table.pageSize,
    search: table.search || undefined,
  };
  const query = useQuery({
    queryKey: queryKeys.customers.list(params),
    queryFn: () => unwrap(api.GET("/api/v1/customers", { params: { query: params } })),
    placeholderData: keepPreviousData,
  });

  const columns: Column<Customer>[] = [
    {
      id: "name",
      header: labels.customers.columns.name,
      cell: (customer) => <span className="font-medium">{customer.name}</span>,
    },
    {
      id: "phone",
      header: labels.customers.columns.phone,
      cell: (customer) => <span className="numeric">{customer.phone ?? "—"}</span>,
    },
    {
      id: "email",
      header: labels.customers.columns.email,
      cell: (customer) => customer.email ?? <span className="text-muted-foreground">—</span>,
    },
  ];

  return (
    <>
      <PageHeader
        title={labels.nav.customers}
        count={query.data ? labels.customers.count(query.data.total) : undefined}
        actions={
          <Can permission="customers:create">
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
          caption={labels.nav.customers}
          columns={columns}
          rows={query.data?.items}
          rowKey={(customer) => customer.id}
          total={query.data?.total ?? 0}
          page={table.page}
          pageSize={table.pageSize}
          onPageChange={table.setPage}
          loading={query.isFetching}
          onRowClick={(customer) => router.push(`/customers/${customer.id}`)}
          empty={labels.customers.empty}
          search={{
            value: table.search,
            onChange: table.setSearch,
            placeholder: labels.customers.searchPlaceholder,
          }}
        />
      )}
      <PersonFormDialog
        open={creating}
        onOpenChange={setCreating}
        initialKind="customer"
        onSaved={(saved) =>
          router.push(
            `/${saved.kind === "customer" ? "customers" : "suppliers"}/${saved.person.id}`,
          )
        }
      />
    </>
  );
}
