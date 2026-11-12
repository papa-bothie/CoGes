"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { PencilLine } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { FieldError } from "@/components/field-error";
import { Button } from "@/components/ui/button";
import { usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage, isApiError } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { labels } from "@/lib/labels";
import { displayNumber } from "@/lib/units";
import { cn } from "@/lib/utils";

const t = labels.sales.correction;

/**
 * Secondes qui restent, à partir de celles que le serveur a données à `receivedAt`.
 *
 * Le délai est celui du serveur (ADR 0119) : le téléphone ne fait que mesurer le temps
 * écoulé depuis la réponse, jamais l'heure de la vente. `null` quand c'est fini.
 */
export function secondsLeft(
  serverSeconds: number | null | undefined,
  receivedAt: number,
  now: number,
): number | null {
  if (serverSeconds == null) return null;
  const left = serverSeconds - Math.floor(Math.max(0, now - receivedAt) / 1000);
  return left > 0 ? left : null;
}

function useSecondsLeft(serverSeconds: number | null | undefined, receivedAt: number) {
  const [now, setNow] = useState(receivedAt);
  useEffect(() => {
    if (serverSeconds == null) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [serverSeconds]);
  return secondsLeft(serverSeconds, receivedAt, now);
}

/**
 * « Corriger cette vente » (ADR 0119) : pendant 10 minutes après l'encaissement, pour qui
 * peut vendre. Une confirmation dit ce qui va se passer, puis le brouillon de la correction
 * s'ouvre. Rien ne s'affiche hors délai, ni sans le droit de vendre.
 */
export function CorrectSale({
  sale,
  receivedAt,
  className,
}: {
  sale: Schemas["SaleRead"];
  /** Moment (horloge du téléphone) où `sale` a été reçue : le décompte part de là. */
  receivedAt: number;
  className?: string;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const canSell = usePermission({ allOf: ["sales:create", "sales:confirm"] });
  const left = useSecondsLeft(sale.correction_seconds_left, receivedAt);
  const idempotency = useIdempotencyKey();
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draftId, setDraftId] = useState<string | null>(null);

  const correct = useMutation({
    meta: { toastError: false },
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/sales/{sale_id}/correct", {
          params: { path: { sale_id: sale.id } },
          body: {},
          headers: idempotency.headers,
        }),
      ),
    onSuccess: (draft) => {
      idempotency.renew();
      for (const key of [queryKeys.sales.all, queryKeys.stock.all, queryKeys.dashboard]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      router.push(`/sales/${draft.id}/edit`);
    },
    onError: (failure) => {
      setError(errorMessage(failure));
      if (isApiError(failure) && failure.code === "sale_already_corrected") {
        const id = failure.details.draft_id;
        setDraftId(typeof id === "string" ? id : null);
      }
    },
  });

  if (!canSell || (left === null && !asking)) return null;

  if (!asking) {
    return (
      <button
        type="button"
        onClick={() => setAsking(true)}
        className={cn(
          "flex min-h-24 flex-[1_1_150px] flex-col items-center justify-center gap-1 rounded-[18px] border-2 border-ventes-anneau bg-ventes-teinte p-2.5 text-center font-bold text-ventes-encre",
          "outline-none hover:border-ventes focus-visible:ring-3 focus-visible:ring-ring/50",
          className,
        )}
      >
        <PencilLine className="size-7" aria-hidden />
        {t.button}
        <span className="text-sm font-semibold">{t.left(left ?? 0)}</span>
      </button>
    );
  }

  return (
    <section
      aria-labelledby={`correct-${sale.id}`}
      className="flex basis-full flex-col gap-3.5 rounded-carte border-2 border-ventes-anneau bg-card p-5 text-left"
    >
      <h2 id={`correct-${sale.id}`} className="text-titre-carte text-ventes-encre">
        {t.question(displayNumber(sale.sale_no))}
      </h2>
      <p className="text-muted-foreground">{t.hint}</p>
      <FieldError message={error} />
      {draftId && (
        <Link
          href={`/sales/${draftId}/edit`}
          className="self-start font-bold text-ventes underline-offset-4 hover:underline"
        >
          {t.openDraft}
        </Link>
      )}
      <div className="flex flex-wrap gap-2.5">
        <Button
          variant="ventes"
          size="standard"
          className="flex-[1_1_220px] text-lg"
          disabled={correct.isPending || draftId !== null}
          onClick={() => correct.mutate()}
        >
          {t.yes}
        </Button>
        <Button
          variant="secondaire"
          size="standard"
          className="flex-[1_1_220px] text-lg"
          onClick={() => {
            setAsking(false);
            setError(null);
          }}
        >
          {t.no}
        </Button>
      </div>
    </section>
  );
}
