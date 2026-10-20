"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { Chip } from "@/components/kit/chip";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage, toApiError } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { attachmentName, periodName, salesPeriod, saveBlob, type SalesPeriod } from "@/lib/files";
import { formatDayMonth } from "@/lib/format";
import { labels } from "@/lib/labels";
import { todayIn } from "@/lib/period";
import { cn } from "@/lib/utils";

type Export = Schemas["ExportRead"];
type Report = Schemas["ImportReport"];
type Referential = "products" | "customers" | "suppliers";
const t = labels.settingsScreens.files;

const PERIODS: readonly [SalesPeriod, string][] = [
  ["month", t.thisMonth],
  ["last", t.lastMonth],
  ["year", t.thisYear],
];
const LISTS: readonly [Referential, string][] = [
  ["products", t.products],
  ["customers", t.customers],
  ["suppliers", t.suppliers],
];

const outline =
  "inline-flex min-h-[54px] w-full items-center justify-center gap-2 rounded-champ border-2 border-input bg-card px-5 font-bold outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50";

/** Les 24 h d'un fichier préparé passées, il n'est plus servi (ADR 0041). */
function isExpired(file: Export, now: Date = new Date()): boolean {
  return file.status === "expired" || new Date(file.expires_at) <= now;
}

/**
 * Fichiers Excel, maquette v2 (écran 24e) : les ventes d'une période (préparées par le
 * worker, ADR 0041), le modèle et l'envoi d'articles en deux temps (vérifier, puis
 * ajouter), et les listes d'articles, de clients et de fournisseurs.
 */
export function FilesView() {
  const canExport = usePermission("importexport:export");
  const canImport = usePermission("importexport:create");
  return (
    <div className="flex flex-col gap-3.5">
      <h2 className="text-titre-carte">{t.title}</h2>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-3">
        {canExport && <SalesCard />}
        {canImport && <ImportCard />}
        {canExport && <ListsCard />}
      </div>
      {canExport && <PreparedFiles />}
    </div>
  );
}

function SalesCard() {
  const { timeZone } = useCompanyLocale();
  const queryClient = useQueryClient();
  const [period, setPeriod] = useState<SalesPeriod>("month");
  // Une demande rejouée (double clic, réseau coupé) rend le même export (ADR 0088).
  const idempotency = useIdempotencyKey();
  const request = useMutation({
    mutationFn: () => {
      const { from, to } = salesPeriod(period, todayIn(timeZone));
      return unwrap(
        api.POST("/api/v1/exports/sales", {
          body: { date_from: from, date_to: to, format: "xlsx" },
          headers: idempotency.headers,
        }),
      );
    },
    onSuccess: () => {
      idempotency.renew();
      toast.success(t.prepared);
      void queryClient.invalidateQueries({ queryKey: queryKeys.exports });
    },
  });
  return (
    <div className="flex flex-col gap-2.5 rounded-tuile bg-ventes-teinte p-[18px]">
      <h3 className="text-lg font-extrabold">{t.sales}</h3>
      <div role="group" aria-label={t.sales} className="flex flex-wrap gap-2">
        {PERIODS.map(([value, label]) => (
          <Chip
            key={value}
            selected={period === value}
            className="text-[15px]"
            onClick={() => setPeriod(value)}
          >
            {label}
          </Chip>
        ))}
      </div>
      <button
        type="button"
        disabled={request.isPending}
        onClick={() => request.mutate()}
        className="inline-flex min-h-[54px] items-center justify-center gap-2 rounded-champ bg-primary px-5 font-bold text-primary-foreground outline-none hover:bg-primary/90 focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
      >
        {request.isPending && <Loader2 className="size-4 animate-spin" aria-hidden />}
        {t.prepare}
      </button>
    </div>
  );
}

/** Le modèle, puis le fichier rempli : vérifié d'abord (`dry_run`), ajouté ensuite. */
function ImportCard() {
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const idempotency = useIdempotencyKey();
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<Report | null>(null);

  const send = useMutation({
    meta: { toastError: false },
    mutationFn: async ({ chosen, dryRun }: { chosen: File; dryRun: boolean }) => {
      const body = new FormData();
      body.append("file", chosen);
      const { data, error, response } = await api.POST("/api/v1/imports/{kind}", {
        params: { path: { kind: "products" }, query: { dry_run: dryRun } },
        headers: idempotency.headers,
        body: body as never,
        bodySerializer: (value: unknown) => value as FormData,
      });
      // Un fichier fautif répond 422 avec le rapport ligne par ligne (ADR 0041).
      const details = (error as { error?: { details?: Partial<Report> } } | undefined)?.error
        ?.details;
      if (!response.ok && Array.isArray(details?.errors)) return details as Report;
      if (!response.ok) throw toApiError(response.status, error);
      return data as Report;
    },
    onSuccess: (result, { dryRun }) => {
      setReport(result);
      if (!dryRun && result.errors.length === 0) {
        toast.success(t.imported(result.created));
        idempotency.renew();
        setFile(null);
        setReport(null);
        void queryClient.invalidateQueries();
      }
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const template = useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/imports/{kind}/template", {
        params: { path: { kind: "products" } },
        parseAs: "blob",
      });
      if (!response.ok || !data) throw toApiError(response.status, error);
      saveBlob(
        data,
        attachmentName(response.headers.get("Content-Disposition"), "modele-products.csv"),
      );
    },
  });

  return (
    <div className="flex flex-col gap-2.5 rounded-tuile bg-depenses-teinte p-[18px]">
      <h3 className="text-lg font-extrabold">{t.bulk}</h3>
      <p className="text-encre-2">{t.bulkHint}</p>
      <button
        type="button"
        disabled={template.isPending}
        onClick={() => template.mutate()}
        className={outline}
      >
        {t.template}
      </button>
      <input
        ref={input}
        type="file"
        accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        onChange={(event) => {
          const chosen = event.target.files?.[0] ?? null;
          event.target.value = "";
          if (!chosen) return;
          idempotency.renew();
          setFile(chosen);
          setReport(null);
          send.mutate({ chosen, dryRun: true });
        }}
      />
      <button
        type="button"
        disabled={send.isPending}
        onClick={() => input.current?.click()}
        className="inline-flex min-h-[54px] items-center justify-center gap-2 rounded-champ bg-depenses px-5 font-bold text-primary-foreground outline-none hover:brightness-95 focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
      >
        {send.isPending && <Loader2 className="size-4 animate-spin" aria-hidden />}
        {send.isPending ? t.checking : t.send}
      </button>
      {report && (
        <div role="status" className="rounded-champ bg-card p-3.5">
          {report.errors.length > 0 ? (
            <>
              <p className="font-bold">{t.problems}</p>
              <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm">
                {report.errors.slice(0, 8).map((problem) => (
                  <li key={`${problem.row}-${problem.column ?? ""}-${problem.code}`}>
                    {t.row(problem.row)} : {problem.message}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <>
              <p className="font-bold">{t.checked(report.created)}</p>
              {file && (
                <button
                  type="button"
                  disabled={send.isPending}
                  onClick={() => send.mutate({ chosen: file, dryRun: false })}
                  className="mt-2.5 inline-flex min-h-cible items-center gap-2 rounded-champ bg-primary px-5 font-bold text-primary-foreground outline-none hover:bg-primary/90 focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
                >
                  {t.confirm}
                </button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function ListsCard() {
  const download = useMutation({
    mutationFn: async (kind: Referential) => {
      const { data, error, response } = await api.GET("/api/v1/exports/referentials/{kind}", {
        params: { path: { kind }, query: { format: "xlsx" } },
        parseAs: "blob",
      });
      if (!response.ok || !data) throw toApiError(response.status, error);
      saveBlob(data, attachmentName(response.headers.get("Content-Disposition"), `${kind}.xlsx`));
    },
  });
  return (
    <div className="flex flex-col gap-2.5 rounded-tuile bg-clients-teinte p-[18px]">
      <h3 className="text-lg font-extrabold">{t.lists}</h3>
      {LISTS.map(([kind, label]) => (
        <button
          key={kind}
          type="button"
          disabled={download.isPending}
          onClick={() => download.mutate(kind)}
          className={outline}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function PreparedFiles() {
  const { timeZone } = useCompanyLocale();
  const query = useQuery({
    queryKey: queryKeys.exports,
    queryFn: () => unwrap(api.GET("/api/v1/exports", { params: { query: { limit: 10 } } })),
    // Un fichier en préparation est relu toutes les 2 s, jusqu'à ce qu'il soit prêt.
    refetchInterval: (current) =>
      current.state.data?.items.some((file) => file.status === "pending") ? 2000 : false,
  });
  const download = useMutation({
    mutationFn: async (file: Export) => {
      const { data, error, response } = await api.GET("/api/v1/exports/{export_id}/file", {
        params: { path: { export_id: file.id } },
        parseAs: "blob",
      });
      if (!response.ok || !data) throw toApiError(response.status, error);
      saveBlob(
        data,
        attachmentName(response.headers.get("Content-Disposition"), file.filename ?? "ventes.xlsx"),
      );
    },
  });

  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const files = (query.data?.items ?? []).filter((file) => file.kind === "sales");
  return (
    <>
      <h3 className="mt-1.5 text-lg font-bold">{t.preparedTitle}</h3>
      {!query.data ? (
        <Skeleton className="h-20 w-full rounded-champ" />
      ) : files.length === 0 ? (
        <p className="border-t border-filet py-3.5 text-muted-foreground">{t.none}</p>
      ) : (
        <ul>
          {files.map((file) => {
            const params = file.params as { date_from?: string; date_to?: string };
            const name =
              params.date_from && params.date_to
                ? t.salesOf(periodName(params.date_from, params.date_to))
                : (file.filename ?? t.sales);
            const expired = isExpired(file);
            const when =
              file.status === "pending"
                ? t.askedNow
                : t.preparedOn(formatDayMonth(file.completed_at ?? file.created_at, timeZone));
            return (
              <li
                key={file.id}
                className="flex flex-wrap items-center gap-3 border-t border-filet py-3.5"
              >
                <div className="min-w-0 flex-1">
                  <div className="font-bold">{name}</div>
                  <div className="text-muted-foreground">{when}</div>
                </div>
                {file.status === "pending" ? (
                  <span className="font-bold text-depenses-encre">{t.pending}</span>
                ) : file.status === "failed" ? (
                  <span className="font-bold text-destructive">{t.failed}</span>
                ) : expired ? (
                  <span className="text-muted-foreground">{t.expired}</span>
                ) : (
                  <button
                    type="button"
                    disabled={download.isPending}
                    onClick={() => download.mutate(file)}
                    className={cn(
                      "inline-flex min-h-[54px] items-center rounded-champ bg-primary px-5 font-bold text-primary-foreground outline-none hover:bg-primary/90 focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50",
                    )}
                  >
                    {t.download}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
