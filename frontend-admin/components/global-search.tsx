"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { api, unwrap } from "@/lib/api/client";

export type SearchHit = {
  key: string;
  label: string;
  detail: string;
  kind: "Entreprise" | "Utilisateur" | "Équipe";
  href: string;
};

export const SEARCH_DELAY_MS = 300;
const MIN_LENGTH = 2;

/** Entreprises, comptes commerçants et équipe en une recherche (prompt 27, D1.1). */
export async function searchEverything(term: string): Promise<SearchHit[]> {
  const needle = term.toLocaleLowerCase("fr");
  const [companies, users, team] = await Promise.all([
    unwrap(
      api.GET("/api/v1/platform/companies", {
        params: { query: { search: term, page_size: 5 } },
      }),
    ).catch(() => null),
    unwrap(
      api.GET("/api/v1/platform/users", { params: { query: { q: term, page_size: 5 } } }),
    ).catch(() => null),
    unwrap(api.GET("/api/v1/platform/team")).catch(() => null),
  ]);
  return [
    ...(companies?.items ?? []).map((company) => ({
      key: `c-${company.id}`,
      label: company.name,
      detail: company.slug,
      kind: "Entreprise" as const,
      href: `/companies/${company.id}`,
    })),
    ...(team?.members ?? [])
      .filter((member) =>
        `${member.display_name} ${member.email}`.toLocaleLowerCase("fr").includes(needle),
      )
      .slice(0, 5)
      .map((member) => ({
        key: `t-${member.id}`,
        label: member.display_name,
        detail: member.email,
        kind: "Équipe" as const,
        href: `/team?member=${member.id}`,
      })),
    ...(users?.items ?? []).map((user) => ({
      key: `u-${user.id}`,
      label: user.full_name,
      detail: `${user.company_name}${user.email ? ` · ${user.email}` : ""}`,
      kind: "Utilisateur" as const,
      href: `/users?company=${user.company_id}&q=${encodeURIComponent(user.full_name)}`,
    })),
  ];
}

function typingElsewhere(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

export function GlobalSearch({
  search = searchEverything,
}: {
  search?: (term: string) => Promise<SearchHit[]>;
}) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const listId = useId();
  const [term, setTerm] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState(false);

  // « / » depuis n'importe quelle page met le curseur dans la recherche.
  useEffect(() => {
    function onKey(event: globalThis.KeyboardEvent) {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      if (typingElsewhere(event.target)) return;
      event.preventDefault();
      inputRef.current?.focus();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    const value = term.trim();
    if (value.length < MIN_LENGTH) return;
    let alive = true;
    const timer = window.setTimeout(() => {
      void search(value).then((found) => {
        if (!alive) return;
        setHits(found);
        setActive(0);
        setOpen(true);
      });
    }, SEARCH_DELAY_MS);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [term, search]);

  function go(hit: SearchHit | undefined) {
    if (!hit) return;
    setOpen(false);
    setTerm("");
    setHits(null);
    inputRef.current?.blur();
    router.push(hit.href);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    const count = hits?.length ?? 0;
    if (event.key === "ArrowDown" && count) {
      event.preventDefault();
      setOpen(true);
      setActive((index) => (index + 1) % count);
    } else if (event.key === "ArrowUp" && count) {
      event.preventDefault();
      setActive((index) => (index - 1 + count) % count);
    } else if (event.key === "Enter") {
      event.preventDefault();
      go(hits?.[active]);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  const shown = open && term.trim().length >= MIN_LENGTH && hits !== null;
  const optionId = (index: number) => `${listId}-${index}`;

  return (
    <div className="relative w-full">
      <label htmlFor={inputId} className="sr-only">
        Rechercher une entreprise ou un compte
      </label>
      <Search
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-encre-douce"
      />
      <input
        ref={inputRef}
        id={inputId}
        type="search"
        role="combobox"
        aria-expanded={shown}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={shown && hits?.length ? optionId(active) : undefined}
        aria-keyshortcuts="/"
        autoComplete="off"
        placeholder="Rechercher…  ( / )"
        value={term}
        onChange={(event) => {
          setTerm(event.target.value);
          if (event.target.value.trim().length < MIN_LENGTH) setOpen(false);
        }}
        onFocus={() => hits && setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        onKeyDown={onKeyDown}
        className="min-h-10 w-full rounded-lg border border-champ bg-surface py-2 pr-3 pl-9 text-encre placeholder:text-encre-douce"
      />
      <ul
        id={listId}
        role="listbox"
        aria-label="Résultats"
        hidden={!shown}
        className="absolute top-full right-0 left-0 z-30 mt-1 max-h-96 overflow-auto rounded-xl border border-trait bg-surface p-1 text-encre shadow-lg"
      >
        {hits?.length === 0 && (
          <li
            role="option"
            aria-selected="false"
            aria-disabled="true"
            className="px-3 py-2 text-encre-douce"
          >
            Aucun résultat pour « {term.trim()} ».
          </li>
        )}
        {hits?.map((hit, index) => (
          <li
            key={hit.key}
            id={optionId(index)}
            role="option"
            aria-selected={index === active}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => go(hit)}
            className={`flex cursor-pointer items-baseline justify-between gap-3 rounded-lg px-3 py-2 ${
              index === active ? "bg-voile" : ""
            }`}
          >
            <span className="min-w-0">
              <span className="block truncate font-semibold">{hit.label}</span>
              <span className="block truncate text-sm text-encre-douce">{hit.detail}</span>
            </span>
            <span className="shrink-0 text-sm text-encre-douce">{hit.kind}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
