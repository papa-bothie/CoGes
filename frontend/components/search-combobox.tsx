"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2, Search } from "lucide-react";
import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { Input } from "@/components/ui/input";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

/**
 * Champ de recherche avec liste de résultats (motif ARIA « combobox » + « listbox »).
 * La recherche est faite **par l'API** (`search`), jamais en filtrant une liste locale.
 */
export function SearchCombobox<T>({
  label,
  placeholder,
  queryKey,
  search,
  itemKey,
  renderItem,
  onSelect,
  emptyText = labels.combobox.noResult,
  disabled = false,
  clearOnSelect = true,
  className,
}: {
  label: string;
  placeholder?: string;
  queryKey: readonly unknown[];
  search: (text: string) => Promise<readonly T[]>;
  itemKey: (item: T) => string;
  renderItem: (item: T) => ReactNode;
  onSelect: (item: T) => void;
  emptyText?: string;
  disabled?: boolean;
  clearOnSelect?: boolean;
  className?: string;
}) {
  const id = useId();
  const listId = `${id}-list`;
  const inputRef = useRef<HTMLInputElement>(null);
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const term = useDebouncedValue(text.trim());

  const results = useQuery({
    queryKey: [...queryKey, term],
    queryFn: () => search(term),
    enabled: open,
    staleTime: 10_000,
  });
  const items = results.data ?? [];

  const choose = (item: T) => {
    onSelect(item);
    if (clearOnSelect) setText("");
    setOpen(false);
    inputRef.current?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive((index) => Math.min(index + 1, Math.max(items.length - 1, 0)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter" && open && items[active]) {
      event.preventDefault();
      choose(items[active]);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div className={cn("relative", className)}>
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <Search
        className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
      <Input
        ref={inputRef}
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={
          open && items[active] ? `${id}-${itemKey(items[active])}` : undefined
        }
        autoComplete="off"
        placeholder={placeholder ?? label}
        value={text}
        disabled={disabled}
        onChange={(event) => {
          setText(event.target.value);
          setActive(0);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
        className="h-9 pl-8"
      />
      {open && (
        <ul
          id={listId}
          role="listbox"
          aria-label={label}
          className="absolute z-30 mt-1 max-h-72 w-full overflow-auto rounded-lg border bg-popover p-1 text-popover-foreground shadow-md"
        >
          {results.isPending ? (
            <li className="flex items-center gap-2 px-2 py-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              {labels.table.loading}
            </li>
          ) : items.length === 0 ? (
            <li className="px-2 py-2 text-sm text-muted-foreground">{emptyText}</li>
          ) : (
            items.map((item, index) => (
              <li
                key={itemKey(item)}
                id={`${id}-${itemKey(item)}`}
                role="option"
                aria-selected={index === active}
                // `mousedown` plutôt que `click` : le `blur` du champ fermerait la liste avant.
                onMouseDown={(event) => {
                  event.preventDefault();
                  choose(item);
                }}
                onMouseEnter={() => setActive(index)}
                className={cn(
                  "cursor-pointer rounded-md px-2 py-1.5 text-sm",
                  index === active && "bg-muted",
                )}
              >
                {renderItem(item)}
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
