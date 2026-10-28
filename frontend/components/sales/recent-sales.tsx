"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, CircleX, Undo2 } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";

import { Avatar, ListRow } from "@/components/kit/list-row";
import { StatusPill } from "@/components/kit/status-pill";
import { Skeleton } from "@/components/ui/skeleton";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import { formatAmount, formatClock } from "@/lib/format";
import { labels } from "@/lib/labels";
import { salePill } from "@/lib/sale-status";
import { displayNumber } from "@/lib/units";
import { cn } from "@/lib/utils";

const t = labels.sales.recent;
/** Huit ventes : assez pour retrouver celle d'il y a un instant, sans faire défiler. */
const LIMIT = 8;

/**
 * « Dernières ventes » sur l'écran Vendre (prompt 28, C4, ADR 0100) : les 8 dernières ventes
 * de l'entreprise, sans brouillon, par la route de liste existante. Un toucher ouvre la
 * vente ; le bloc se replie ; une erreur de chargement reste dans le bloc et n'empêche
 * jamais de vendre. Actualisé après chaque vente confirmée ou annulée (`sales.all`).
 */
export function RecentSales({ currency, timeZone }: { currency: string; timeZone: string }) {
  const [open, setOpen] = useState(true);
  const regionId = useId();
  const query = useQuery({
    queryKey: queryKeys.sales.list({ recent: true }),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/sales", {
          params: { query: { include_drafts: false, page: 1, page_size: LIMIT } },
        }),
      ),
  });

  return (
    <section className="rounded-carte border border-border bg-card p-4">
      <h2>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={regionId}
          onClick={() => setOpen((value) => !value)}
          className="flex min-h-cible w-full items-center justify-between gap-2 rounded-touche text-left text-libelle outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {t.title}
          <ChevronDown
            aria-hidden
            className={cn(
              "size-5 transition-transform motion-reduce:transition-none",
              open && "rotate-180",
            )}
          />
        </button>
      </h2>
      {open && (
        <div id={regionId} className="mt-2 flex flex-col gap-1">
          {query.isPending ? (
            <div className="flex flex-col gap-2" aria-busy="true">
              {Array.from({ length: 3 }, (_, index) => (
                <Skeleton key={index} className="h-14 w-full rounded-tuile" />
              ))}
            </div>
          ) : query.isError ? (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-champ bg-voile px-3 py-2.5">
              <p className="font-semibold">{t.error}</p>
              <button
                type="button"
                onClick={() => void query.refetch()}
                className="min-h-cible rounded-touche px-3 font-bold text-ventes-encre outline-none hover:bg-card focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                {t.retry}
              </button>
            </div>
          ) : query.data.items.length === 0 ? (
            <p className="py-3 text-muted-foreground">{t.empty}</p>
          ) : (
            <ul className="flex flex-col">
              {query.data.items.map((sale) => {
                const pill = salePill(sale, currency);
                const Icon =
                  pill?.status === "cancelled"
                    ? CircleX
                    : pill?.status === "returned"
                      ? Undo2
                      : null;
                return (
                  <li key={sale.id}>
                    <ListRow
                      href={`/sales/${sale.id}`}
                      wrap
                      leading={<Avatar name={sale.customer_name} rubrique="clients" />}
                      title={sale.customer_name ?? labels.sales.anonymous}
                      subtitle={
                        // L'état passe sous le numéro : à 360 px, il va à la ligne au lieu de
                        // déborder.
                        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          <span>
                            {t.line(
                              displayNumber(sale.sale_no),
                              formatClock(sale.sold_at, timeZone),
                            )}
                          </span>
                          {pill && (
                            <span className="inline-flex items-center gap-1">
                              {Icon && (
                                <Icon
                                  aria-hidden
                                  data-state={pill.status}
                                  className="size-4 text-muted-foreground"
                                />
                              )}
                              <StatusPill status={pill.status} amount={pill.amount} />
                            </span>
                          )}
                        </span>
                      }
                      trailing={
                        <span
                          className={cn(
                            "font-extrabold numeric",
                            sale.status === "cancelled" && "line-through",
                          )}
                        >
                          {formatAmount(sale.total, currency)}
                        </span>
                      }
                    />
                  </li>
                );
              })}
            </ul>
          )}
          <Link
            href="/sales"
            className="mt-1 inline-flex min-h-cible items-center self-start font-bold text-ventes underline underline-offset-2 hover:text-ventes-encre"
          >
            {t.seeAll}
          </Link>
        </div>
      )}
    </section>
  );
}
