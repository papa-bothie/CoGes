"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { ErrorState } from "@/components/error-state";
import { NotificationItem } from "@/components/notifications/notification-item";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import { labels } from "@/lib/labels";

/** Fil personnel d'alertes, paginé, filtrable sur les non lues. */
export function NotificationsView() {
  const table = useTableParams();
  const unreadOnly = table.get("unread") === "1";
  const params = { page: table.page, page_size: table.pageSize, unread: unreadOnly || undefined };
  const query = useQuery({
    queryKey: queryKeys.notifications.list(params),
    queryFn: () => unwrap(api.GET("/api/v1/notifications", { params: { query: params } })),
    placeholderData: keepPreviousData,
  });
  const t = labels.notifications;
  const pages = Math.max(1, Math.ceil((query.data?.total ?? 0) / table.pageSize));

  return (
    <>
      <PageHeader
        title={labels.nav.notifications}
        count={query.data ? t.count(query.data.total) : undefined}
      />
      <Tabs
        value={unreadOnly ? "unread" : "all"}
        onValueChange={(value) => table.setFilter("unread", value === "unread" ? "1" : null)}
      >
        <TabsList aria-label={t.filter}>
          <TabsTrigger value="all">{t.all}</TabsTrigger>
          <TabsTrigger value="unread">{t.unreadOnly}</TabsTrigger>
        </TabsList>
      </Tabs>
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : !query.data ? (
        <Skeleton className="h-96 w-full" />
      ) : query.data.items.length === 0 ? (
        <p className="rounded-xl border border-dashed bg-card py-10 text-center text-sm text-muted-foreground">
          {t.empty}
        </p>
      ) : (
        <ul className="divide-y overflow-hidden rounded-xl border bg-card">
          {query.data.items.map((notification) => (
            <NotificationItem key={notification.id} notification={notification} />
          ))}
        </ul>
      )}
      {pages > 1 && (
        <div className="flex items-center justify-end gap-2 text-sm text-muted-foreground">
          {labels.table.pageOf(table.page, pages)}
          <Button
            variant="outline"
            size="icon-sm"
            aria-label={labels.table.previous}
            disabled={table.page <= 1}
            onClick={() => table.setPage(table.page - 1)}
          >
            <ChevronLeft />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            aria-label={labels.table.next}
            disabled={table.page >= pages}
            onClick={() => table.setPage(table.page + 1)}
          >
            <ChevronRight />
          </Button>
        </div>
      )}
    </>
  );
}
