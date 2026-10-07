"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { Loader2, Plus, Search } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { CustomerFormDialog } from "@/components/customers/customer-form-dialog";
import { Input } from "@/components/ui/input";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal } from "@/lib/decimal";
import { formatMoney } from "@/lib/format";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

type Choice = Schemas["CustomerChoice"];

/** Ce que la vente retient du client choisi ; `null` = client de passage. */
export type PickedCustomer = { id: string; name: string };

/** Une page de 50 : assez pour une boutique, et la suite arrive au défilement. */
export const CUSTOMER_PAGE_SIZE = 50;

type Option = { key: string; choice: Choice | null };

export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  return words
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() ?? "")
    .join("");
}

/**
 * Choix du client d'une vente (bug B3 de la phase 15, ADR 0063).
 *
 * - La liste s'ouvre dans une **couche au-dessus de la page** (Popover, portail) : la
 *   carte qui l'entoure ne la rogne plus.
 * - Champ vide : « Client de passage », puis les clients récents, puis tous les autres
 *   par ordre alphabétique, chargés par pages de 50 au défilement.
 * - Chaque ligne montre l'avatar, le nom, le téléphone et ce que le client doit.
 * - « Nouveau client » ouvre la fiche courte et revient à la vente avec ce client.
 */
export function CustomerPicker({
  onSelect,
  disabled = false,
  currency,
}: {
  onSelect: (customer: PickedCustomer | null) => void;
  disabled?: boolean;
  currency?: string;
}) {
  const id = useId();
  const listId = `${id}-list`;
  const anchorRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const sentinelRef = useRef<HTMLLIElement>(null);
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [creating, setCreating] = useState(false);
  const term = useDebouncedValue(text.trim());

  const query = useInfiniteQuery({
    queryKey: queryKeys.customers.choices(term),
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/sales/customer-choices", {
          params: {
            query: { search: term || undefined, page: pageParam, page_size: CUSTOMER_PAGE_SIZE },
          },
        }),
      ),
    initialPageParam: 1,
    getNextPageParam: (last, pages) =>
      pages.reduce((count, page) => count + page.items.length, 0) < last.total
        ? last.page + 1
        : undefined,
    enabled: open,
    staleTime: 10_000,
  });

  const options: Option[] = [
    ...(term ? [] : [{ key: "walk-in", choice: null }]),
    ...(query.data?.pages ?? []).flatMap((page) =>
      page.items.map((choice) => ({ key: choice.id, choice })),
    ),
  ];

  // La page suivante se charge quand le bas de la liste devient visible.
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = query;
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!open || !sentinel || !hasNextPage || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting) && !isFetchingNextPage) {
          void fetchNextPage();
        }
      },
      { root: listRef.current, rootMargin: "128px" },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [open, hasNextPage, isFetchingNextPage, fetchNextPage, options.length]);

  const choose = (option: Option) => {
    onSelect(option.choice ? { id: option.choice.id, name: option.choice.name } : null);
    setText("");
    setOpen(false);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive((index) => Math.min(index + 1, Math.max(options.length - 1, 0)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter" && open && options[active]) {
      event.preventDefault();
      choose(options[active]);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  };

  const activeOption = open ? options[active] : undefined;

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverAnchor asChild>
          <div ref={anchorRef} className="relative">
            <label htmlFor={id} className="sr-only">
              {labels.sales.customerSearch}
            </label>
            <Search
              className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              id={id}
              role="combobox"
              aria-expanded={open}
              aria-controls={listId}
              aria-autocomplete="list"
              aria-activedescendant={activeOption ? `${id}-${activeOption.key}` : undefined}
              autoComplete="off"
              placeholder={labels.sales.customerSearch}
              value={text}
              disabled={disabled}
              onChange={(event) => {
                setText(event.target.value);
                setActive(0);
                setOpen(true);
              }}
              onFocus={() => setOpen(true)}
              onClick={() => setOpen(true)}
              onKeyDown={onKeyDown}
              className="h-9 pl-8"
            />
          </div>
        </PopoverAnchor>
        <PopoverContent
          className="w-(--radix-popover-trigger-width) min-w-72 p-0"
          // Le focus reste dans le champ : on tape, la liste suit.
          onOpenAutoFocus={(event) => event.preventDefault()}
          onCloseAutoFocus={(event) => event.preventDefault()}
          onInteractOutside={(event) => {
            if (anchorRef.current?.contains(event.target as Node)) event.preventDefault();
          }}
        >
          <ul
            ref={listRef}
            id={listId}
            role="listbox"
            aria-label={labels.sales.customerSearch}
            className="max-h-[min(24rem,60vh)] overflow-y-auto overscroll-contain p-1"
          >
            {options.map((option, index) => (
              <li
                key={option.key}
                id={`${id}-${option.key}`}
                role="option"
                aria-selected={index === active}
                // Le champ garde le focus : la liste ne se ferme pas sous le doigt.
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(option)}
                onMouseEnter={() => setActive(index)}
                className={cn(
                  "flex min-h-16 cursor-pointer items-center gap-3 rounded-md px-3 py-2",
                  index === active && "bg-muted",
                )}
              >
                <CustomerRow choice={option.choice} currency={currency} />
              </li>
            ))}
            {query.isPending || isFetchingNextPage ? (
              <li
                role="presentation"
                className="flex items-center gap-2 px-3 py-3 text-sm text-muted-foreground"
              >
                <Loader2 className="size-4 animate-spin" aria-hidden />
                {isFetchingNextPage
                  ? labels.sales.customerPicker.loadingMore
                  : labels.table.loading}
              </li>
            ) : (
              options.length === 0 && (
                <li role="presentation" className="px-3 py-3 text-sm text-muted-foreground">
                  {labels.combobox.noResult}
                </li>
              )
            )}
            <li ref={sentinelRef} role="presentation" aria-hidden className="h-px" />
          </ul>
          <div className="border-t p-1">
            <button
              type="button"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => {
                setOpen(false);
                setCreating(true);
              }}
              className="flex min-h-12 w-full items-center gap-2 rounded-md px-3 font-medium outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <Plus className="size-4" aria-hidden />
              {labels.sales.customerPicker.newCustomer}
            </button>
          </div>
        </PopoverContent>
      </Popover>
      <CustomerFormDialog
        open={creating}
        onOpenChange={setCreating}
        onSaved={(customer) => onSelect({ id: customer.id, name: customer.name })}
      />
    </>
  );
}

function CustomerRow({ choice, currency }: { choice: Choice | null; currency?: string }) {
  const name = choice?.name ?? labels.sales.noCustomer;
  const owes = choice !== null && compareDecimal(choice.open_debt, "0") === 1;
  return (
    <>
      <span
        aria-hidden
        className={cn(
          "flex size-10 shrink-0 items-center justify-center rounded-full text-sm font-semibold",
          choice ? "bg-ventes-teinte text-ventes-encre" : "bg-muted text-muted-foreground",
        )}
      >
        {choice ? initials(choice.name) : "·"}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium">{name}</span>
        <span className="block truncate text-sm numeric text-muted-foreground">
          {choice ? choice.phone : labels.sales.customerPicker.walkInHint}
        </span>
      </span>
      {owes && (
        <span className="shrink-0 text-sm font-semibold numeric whitespace-nowrap text-warning-ink">
          {labels.sales.customerPicker.owes(formatMoney(choice.open_debt, currency))}
        </span>
      )}
    </>
  );
}
