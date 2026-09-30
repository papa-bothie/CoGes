"use client";

import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { useEffect, useState, type KeyboardEvent, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

export type Column<T> = {
  id: string;
  header: string;
  cell: (row: T) => ReactNode;
  /** Montants et quantités : alignés à droite, chiffres tabulaires, jamais coupés. */
  numeric?: boolean;
  /** Le tri n'est proposé que si l'API sait trier sur cette colonne. */
  sortable?: boolean;
  className?: string;
};

export type SortState = { id: string; direction: "asc" | "desc" } | null;

export type DataTableProps<T> = {
  caption: string;
  columns: readonly Column<T>[];
  rows: readonly T[] | undefined;
  rowKey: (row: T) => string;
  /** Pagination **côté serveur** : total renvoyé par l'API, page courante (1-based). */
  total: number;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  sort?: SortState;
  onSortChange?: (sort: SortState) => void;
  search?: { value: string; onChange: (value: string) => void; placeholder?: string };
  /** Listes déroulantes de filtres, rendues à droite de la recherche. */
  filters?: ReactNode;
  loading?: boolean;
  onRowClick?: (row: T) => void;
  /** Classe d'une ligne (surlignage d'un seuil, par exemple). */
  rowClassName?: (row: T) => string | undefined;
  empty?: ReactNode;
};

function nextSort(current: SortState | undefined, id: string): SortState {
  if (!current || current.id !== id) return { id, direction: "asc" };
  return current.direction === "asc" ? { id, direction: "desc" } : null;
}

function SearchBox({
  value,
  onChange,
  placeholder,
}: NonNullable<DataTableProps<unknown>["search"]>) {
  const [text, setText] = useState(value);
  const debounced = useDebouncedValue(text);
  useEffect(() => {
    if (debounced !== value) onChange(debounced);
    // `value` peut changer de l'extérieur (réinitialisation) : on ne suit que la saisie.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);
  return (
    <div className="relative w-full max-w-sm">
      <Search
        className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
      <Input
        type="search"
        aria-label={placeholder ?? labels.table.search}
        placeholder={placeholder ?? labels.table.search}
        value={text}
        onChange={(event) => setText(event.target.value)}
        className="pl-8"
      />
    </div>
  );
}

export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  total,
  page,
  pageSize,
  onPageChange,
  sort,
  onSortChange,
  search,
  filters,
  loading = false,
  onRowClick,
  rowClassName,
  empty,
}: DataTableProps<T>) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const showSkeleton = loading && !rows;

  const handleRowKey = (event: KeyboardEvent<HTMLTableRowElement>, row: T) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onRowClick?.(row);
    }
  };

  return (
    <div className="space-y-3">
      {(search || filters) && (
        <div className="flex flex-wrap items-center gap-2">
          {search && <SearchBox {...search} />}
          {filters}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border bg-card">
        <Table aria-busy={loading}>
          <TableCaption className="sr-only">{caption}</TableCaption>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              {columns.map((column) => {
                const active = sort?.id === column.id ? sort.direction : null;
                const canSort = column.sortable && onSortChange;
                return (
                  <TableHead
                    key={column.id}
                    scope="col"
                    aria-sort={
                      active === "asc" ? "ascending" : active === "desc" ? "descending" : undefined
                    }
                    className={cn("h-10 px-4", column.numeric && "text-right", column.className)}
                  >
                    {canSort ? (
                      <button
                        type="button"
                        onClick={() => onSortChange(nextSort(sort, column.id))}
                        className={cn(
                          "-mx-1 inline-flex items-center gap-1 rounded px-1 outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50",
                          column.numeric && "flex-row-reverse",
                        )}
                      >
                        {column.header}
                        {active === "asc" ? (
                          <ArrowUp className="size-3.5" aria-label={labels.table.sortAscending} />
                        ) : active === "desc" ? (
                          <ArrowDown
                            className="size-3.5"
                            aria-label={labels.table.sortDescending}
                          />
                        ) : (
                          <ArrowUpDown className="size-3.5 opacity-50" aria-hidden />
                        )}
                      </button>
                    ) : (
                      column.header
                    )}
                  </TableHead>
                );
              })}
            </TableRow>
          </TableHeader>
          <TableBody>
            {showSkeleton &&
              Array.from({ length: Math.min(pageSize, 5) }, (_, index) => (
                <TableRow key={`skeleton-${index}`}>
                  {columns.map((column) => (
                    <TableCell key={column.id} className="px-4">
                      <Skeleton className={cn("h-4", column.numeric ? "ml-auto w-16" : "w-32")} />
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            {!showSkeleton && rows?.length === 0 && (
              <TableRow className="hover:bg-transparent">
                <TableCell
                  colSpan={columns.length}
                  className="h-24 text-center text-muted-foreground"
                >
                  {empty ?? labels.table.empty}
                </TableCell>
              </TableRow>
            )}
            {rows?.map((row) => (
              <TableRow
                key={rowKey(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={onRowClick ? (event) => handleRowKey(event, row) : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                className={cn(
                  rowClassName?.(row),
                  onRowClick &&
                    "cursor-pointer outline-none focus-visible:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset",
                )}
              >
                {columns.map((column) => (
                  <TableCell
                    key={column.id}
                    className={cn("px-4", column.numeric && "text-right numeric", column.className)}
                  >
                    {column.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <nav
        aria-label="Pagination"
        className="flex items-center justify-between gap-2 text-sm text-muted-foreground"
      >
        <span>{labels.table.total(total)}</span>
        <div className="flex items-center gap-2">
          <span aria-live="polite">{labels.table.pageOf(page, pages)}</span>
          <Button
            variant="outline"
            size="icon-sm"
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1 || loading}
            aria-label={labels.table.previous}
          >
            <ChevronLeft />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            onClick={() => onPageChange(page + 1)}
            disabled={page >= pages || loading}
            aria-label={labels.table.next}
          >
            <ChevronRight />
          </Button>
        </div>
      </nav>
    </div>
  );
}
