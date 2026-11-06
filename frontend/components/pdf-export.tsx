"use client";

import { useMutation } from "@tanstack/react-query";
import { FileDown, Loader2 } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";

import { FieldError } from "@/components/field-error";
import { Chip } from "@/components/kit/chip";
import { fieldClasses, type Rubrique } from "@/components/kit/rubrique";
import { SecondaryAction } from "@/components/kit/secondary-action";
import { useCompanyLocale, useMe } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { PDF_EXPORTS } from "@/lib/access";
import { api } from "@/lib/api/client";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { ApiError, errorMessage, toApiError } from "@/lib/api/errors";
import { attachmentName, saveBlob } from "@/lib/files";
import { labels } from "@/lib/labels";
import { can } from "@/lib/permissions";
import {
  pdfPeriod,
  QUEUED_PDFS,
  TOO_LARGE,
  UNDATED_PDFS,
  type PdfKind,
  type PdfPeriod,
  type PdfPeriodChoice,
} from "@/lib/pdf-export";
import { todayIn } from "@/lib/period";

const t = labels.pdfExport;
const CHOICES: readonly PdfPeriodChoice[] = ["day", "week", "month", "custom"];

async function downloadNow(kind: PdfKind, period: PdfPeriod | null): Promise<void> {
  const options = { parseAs: "blob" as const };
  const result =
    kind === "stock"
      ? await api.GET("/api/v1/analytics/stock/pdf", options)
      : kind === "debts"
        ? await api.GET("/api/v1/analytics/debts/pdf", options)
        : await api.GET("/api/v1/analytics/expenses/pdf", {
            ...options,
            params: { query: { from: period!.from, to: period!.to } },
          });
  const { data, error, response } = result;
  if (!response.ok || !(data instanceof Blob)) throw toApiError(response.status, error);
  saveBlob(data, attachmentName(response.headers.get("Content-Disposition"), `${kind}.pdf`));
}

async function requestQueued(
  kind: PdfKind,
  period: PdfPeriod | null,
  headers: Record<string, string>,
): Promise<void> {
  const { error, response } = await api.POST("/api/v1/exports/pdf", {
    headers,
    body: period ? { kind, date_from: period.from, date_to: period.to } : { kind },
  });
  if (!response.ok) throw toApiError(response.status, error);
}

/**
 * « Exporter en PDF » (prompt 35, bloc X, ADR 0114) : masqué sans le droit de lecture de
 * l'écran **et** le droit d'export du document (le serveur revérifie). Les documents
 * datés demandent leur période (aujourd'hui, cette semaine, ce mois, des dates) ; les
 * longs partent au worker et arrivent dans Réglages → Fichiers. Un document immédiat que
 * le serveur juge trop long (`report_too_large`) se prépare de la même façon.
 */
export function PdfExport({ kind, rubrique = "argent" }: { kind: PdfKind; rubrique?: Rubrique }) {
  const allowed = usePermission(PDF_EXPORTS[kind]);
  const { timeZone } = useCompanyLocale();
  const id = useId();
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState<PdfPeriodChoice>("month");
  const [custom, setCustom] = useState({ from: "", to: "" });
  const [error, setError] = useState<string | null>(null);
  const [queued, setQueued] = useState(false);
  // Nombre de lignes d'un document immédiat refusé comme trop long : il passe par la file.
  const [tooLarge, setTooLarge] = useState<number | null>(null);
  const viaQueue = QUEUED_PDFS.includes(kind) || tooLarge !== null;
  const undated = UNDATED_PDFS.includes(kind);
  // Gardée jusqu'au succès : une demande relancée après une coupure n'en fait pas deux.
  const idempotency = useIdempotencyKey();

  const run = useMutation({
    meta: { toastError: false },
    mutationFn: async ({ period, queue }: { period: PdfPeriod | null; queue: boolean }) => {
      if (queue) await requestQueued(kind, period, idempotency.headers);
      else await downloadNow(kind, period);
      return queue;
    },
    onSuccess: (queue) => {
      setError(null);
      if (queue) {
        idempotency.renew();
        setQueued(true);
      } else setOpen(false);
    },
    onError: (failure) => {
      if (failure instanceof ApiError && failure.code === TOO_LARGE) {
        setError(null);
        setTooLarge(Number(failure.details.rows) || 0);
      } else setError(errorMessage(failure));
    },
  });

  if (!allowed) return null;

  const submit = (queue = viaQueue) => {
    if (undated) return run.mutate({ period: null, queue });
    const period = pdfPeriod(choice, todayIn(timeZone), custom);
    if (!period) return setError(t.invalidPeriod);
    setQueued(false);
    run.mutate({ period, queue });
  };

  const queueNotice = (
    <>
      {tooLarge !== null && !queued && <p className="text-encre-2">{t.tooLarge(tooLarge)}</p>}
      {queued && (
        <p role="status" className="text-encre-2">
          {t.queued}{" "}
          <Link href="/settings/files" className="font-bold underline underline-offset-4">
            {t.files}
          </Link>
        </p>
      )}
    </>
  );

  if (undated) {
    return (
      <div className="flex flex-col gap-1.5">
        <SecondaryAction onClick={() => submit(false)} disabled={run.isPending}>
          {run.isPending && !viaQueue ? (
            <Loader2 className="size-5 animate-spin" aria-hidden />
          ) : (
            <FileDown className="size-5" aria-hidden />
          )}
          {t.button}
        </SecondaryAction>
        {tooLarge !== null && !queued && (
          <SecondaryAction onClick={() => submit(true)} disabled={run.isPending}>
            {run.isPending && <Loader2 className="size-5 animate-spin" aria-hidden />}
            {t.prepare}
          </SecondaryAction>
        )}
        <FieldError message={error ?? undefined} />
        {queueNotice}
      </div>
    );
  }

  const field = fieldClasses(rubrique);
  return (
    <div className="flex flex-col gap-2.5">
      <SecondaryAction
        aria-expanded={open}
        aria-controls={`${id}-panel`}
        onClick={() => setOpen((value) => !value)}
      >
        <FileDown className="size-5" aria-hidden />
        {t.button}
      </SecondaryAction>
      {open && (
        <div
          id={`${id}-panel`}
          className="flex flex-col gap-3 rounded-champ border border-filet bg-card p-4"
        >
          <span id={`${id}-label`} className="font-bold">
            {t.period}
          </span>
          <div role="group" aria-labelledby={`${id}-label`} className="flex flex-wrap gap-2">
            {CHOICES.map((value) => (
              <Chip
                key={value}
                rubrique={rubrique}
                selected={choice === value}
                aria-pressed={choice === value}
                onClick={() => setChoice(value)}
              >
                {t.choices[value]}
              </Chip>
            ))}
          </div>
          {choice === "custom" && (
            <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3">
              {(["from", "to"] as const).map((edge) => (
                <label key={edge} className="flex flex-col gap-1 font-bold">
                  {t[edge]}
                  <input
                    type="date"
                    className={field}
                    value={custom[edge]}
                    onChange={(event) =>
                      setCustom((current) => ({ ...current, [edge]: event.target.value }))
                    }
                  />
                </label>
              ))}
            </div>
          )}
          <SecondaryAction onClick={() => submit()} disabled={run.isPending}>
            {run.isPending && <Loader2 className="size-5 animate-spin" aria-hidden />}
            {viaQueue ? t.prepare : t.download}
          </SecondaryAction>
          <FieldError message={error ?? undefined} />
          {queueNotice}
        </div>
      )}
    </div>
  );
}

/**
 * Bloc « Pour votre comptable » au pied d'un écran : ses exports PDF, chacun derrière ses
 * droits ; rien du tout si la personne n'en a aucun.
 */
export function AccountantExports({
  kinds,
  rubrique = "argent",
}: {
  kinds: readonly PdfKind[];
  rubrique?: Rubrique;
}) {
  const { data } = useMe();
  const visible = kinds.filter((kind) => can(data?.permissions, PDF_EXPORTS[kind]));
  if (visible.length === 0) return null;
  return (
    <section aria-label={t.section} className="flex flex-col gap-3 border-t border-filet pt-4">
      <h2 className="text-titre-carte">{t.section}</h2>
      <div className="flex flex-wrap items-start gap-4">
        {visible.map((kind) => (
          <div key={kind} className="flex min-w-0 flex-[1_1_260px] flex-col gap-1.5">
            <span className="text-encre-2">{t.titles[kind]}</span>
            <PdfExport kind={kind} rubrique={rubrique} />
          </div>
        ))}
      </div>
    </section>
  );
}
