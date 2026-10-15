"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Loader2 } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { Chip } from "@/components/kit/chip";
import { fieldClasses } from "@/components/kit/rubrique";
import { ToggleSwitch } from "@/components/kit/toggle-switch";
import { Skeleton } from "@/components/ui/skeleton";
import { ME_QUERY_KEY } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import {
  compareDecimal,
  parseDecimalInput,
  percentToRate,
  rateToPercent,
  toInputDecimal,
} from "@/lib/decimal";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

type Company = Schemas["CompanyRead"];
type ReceiptFormat = "ticket" | "a4";
const t = labels.settingsScreens.shop;

/** Coordonnées imprimées sur le reçu (révision 0016), dans l'ordre de la maquette 24. */
const FIELDS = [
  ["name", t.name, 200],
  ["phone", t.phone, 30],
  ["address", t.address, 200],
  ["wave_number", t.wave, 30],
  ["ninea", t.ninea, 30],
  ["rc", t.rc, 40],
] as const;
type FieldKey = (typeof FIELDS)[number][0] | "receipt_footer";

type Draft = Record<FieldKey, string> & {
  receiptFormat: ReceiptFormat;
  taxEnabled: boolean;
  intelligenceEnabled: boolean;
  reorderPoint: string;
  taxPercent: string;
};

function draftOf(company: Company): Draft {
  const settings = company.settings as Record<string, unknown>;
  const reorder = settings.default_reorder_point;
  const rate = settings.default_tax_rate;
  return {
    name: company.name,
    phone: company.phone ?? "",
    address: company.address ?? "",
    wave_number: company.wave_number ?? "",
    ninea: company.ninea ?? "",
    rc: company.rc ?? "",
    receipt_footer: company.receipt_footer ?? "",
    receiptFormat: settings.receipt_format === "a4" ? "a4" : "ticket",
    // Absent vaut « activé » (ADR 0022, 0036) : l'écran montre le comportement réel.
    taxEnabled: settings.tax_enabled !== false,
    intelligenceEnabled: settings.intelligence_enabled !== false,
    reorderPoint: typeof reorder === "string" ? toInputDecimal(reorder) : "",
    taxPercent: typeof rate === "string" ? rateToPercent(rate) : "",
  };
}

/** « Africa/Dakar » → « Dakar ». */
function cityOf(timeZone: string): string {
  return (timeZone.split("/").at(-1) ?? timeZone).replaceAll("_", " ");
}

/**
 * Ma boutique, maquette v2 (écran 24) : coordonnées du reçu, reçu par défaut, TVA et
 * conseils ; le seuil et la TVA par défaut sous « Plus de réglages ». Pas de logo en V1.
 */
export function ShopView() {
  const query = useQuery({
    queryKey: queryKeys.company,
    queryFn: () => unwrap(api.GET("/api/v1/companies/me")),
  });
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (!query.data) return <Skeleton className="h-[640px] w-full rounded-carte" />;
  return <ShopForm key={query.data.updated_at} company={query.data} />;
}

function ShopForm({ company }: { company: Company }) {
  const queryClient = useQueryClient();
  const canEdit = usePermission("company:update");
  const id = useId();
  const [draft, setDraft] = useState<Draft>(() => draftOf(company));
  const [more, setMore] = useState(false);
  const [errors, setErrors] = useState<{
    name?: string;
    reorder?: string;
    tax?: string;
    form?: string;
  }>({});
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  const save = useMutation({
    meta: { toastError: false },
    mutationFn: (body: Schemas["CompanyUpdate"]) =>
      unwrap(api.PATCH("/api/v1/companies/me", { body })),
    onSuccess: () => {
      for (const key of [
        queryKeys.company,
        ME_QUERY_KEY,
        queryKeys.intelligence.all,
        queryKeys.dashboard,
      ]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      toast.success(t.saved);
    },
    onError: (error) => setErrors({ form: errorMessage(error) }),
  });

  const reorder = draft.reorderPoint.trim() ? parseDecimalInput(draft.reorderPoint) : null;
  // Taux appliqué aux articles créés sans taux (ADR 0066) ; vide = aucun.
  const taxRate = draft.taxPercent.trim() ? percentToRate(draft.taxPercent) : null;

  const submit = () => {
    const next: typeof errors = {};
    if (!draft.name.trim()) next.name = labels.validation.required;
    if (draft.reorderPoint.trim() && (reorder === null || !/^\d+(\.\d{1,3})?$/.test(reorder)))
      next.reorder = t.invalidThreshold;
    if (
      draft.taxPercent.trim() &&
      (taxRate === null ||
        compareDecimal(taxRate, "1") !== -1 ||
        !/^\d+(\.\d{1,4})?$/.test(taxRate))
    )
      next.tax = t.invalidTax;
    setErrors(next);
    if (next.reorder || next.tax) setMore(true);
    if (Object.keys(next).length > 0) return;
    save.mutate({
      name: draft.name.trim(),
      phone: draft.phone,
      address: draft.address,
      wave_number: draft.wave_number,
      ninea: draft.ninea,
      rc: draft.rc,
      receipt_footer: draft.receipt_footer,
      // `settings` remplace l'objet entier (ADR 0054) : les autres clés sont renvoyées.
      settings: {
        ...company.settings,
        receipt_format: draft.receiptFormat,
        tax_enabled: draft.taxEnabled,
        intelligence_enabled: draft.intelligenceEnabled,
        default_reorder_point: reorder,
        default_tax_rate: taxRate,
      },
    });
  };

  const input = cn(fieldClasses("ventes"), "min-h-[54px] px-3.5 text-[17px]");
  const currency = t.currencies[company.currency] ?? company.currency;

  return (
    <form
      className="flex flex-col gap-4"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <h2 className="text-titre-carte">{t.title}</h2>
      <fieldset disabled={!canEdit} className="contents">
        <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-3.5">
          {FIELDS.map(([key, label, max]) => (
            <div key={key}>
              <label htmlFor={`${id}-${key}`} className="mb-1.5 block font-bold">
                {label}
              </label>
              <input
                id={`${id}-${key}`}
                className={input}
                value={draft[key]}
                maxLength={max}
                aria-invalid={key === "name" && Boolean(errors.name)}
                onChange={(event) => set(key, event.target.value)}
              />
              {key === "name" && <FieldError message={errors.name} />}
            </div>
          ))}
        </div>
        <div>
          <label htmlFor={`${id}-footer`} className="mb-1.5 block font-bold">
            {t.footer}
          </label>
          <input
            id={`${id}-footer`}
            className={input}
            value={draft.receipt_footer}
            maxLength={300}
            onChange={(event) => set("receipt_footer", event.target.value)}
          />
        </div>
        <div>
          <span id={`${id}-receipt`} className="mb-1.5 block font-bold">
            {t.receipt}
          </span>
          <div role="group" aria-labelledby={`${id}-receipt`} className="flex flex-wrap gap-2">
            {(["ticket", "a4"] as const).map((format) => (
              <Chip
                key={format}
                selected={draft.receiptFormat === format}
                className="text-[15px]"
                onClick={() => set("receiptFormat", format)}
              >
                {format === "ticket" ? t.ticket : t.a4}
              </Chip>
            ))}
          </div>
        </div>
        <div>
          <ToggleSwitch
            label={t.tax}
            description={draft.taxEnabled ? t.taxOn : t.taxOff}
            checked={draft.taxEnabled}
            disabled={!canEdit}
            onCheckedChange={(value) => set("taxEnabled", value)}
          />
          <ToggleSwitch
            label={t.advice}
            description={t.adviceHint}
            checked={draft.intelligenceEnabled}
            disabled={!canEdit}
            onCheckedChange={(value) => set("intelligenceEnabled", value)}
          />
        </div>
        <div className="rounded-champ border border-filet">
          <button
            type="button"
            aria-expanded={more}
            aria-controls={`${id}-more`}
            onClick={() => setMore((open) => !open)}
            className="flex min-h-cible w-full items-center justify-between gap-3 rounded-champ px-4 font-bold outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {t.more}
            <ChevronDown
              aria-hidden
              className={cn("size-5 transition-transform", more && "rotate-180")}
            />
          </button>
          {more && (
            <div
              id={`${id}-more`}
              className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-3.5 px-4 pb-4"
            >
              <div>
                <label htmlFor={`${id}-reorder`} className="mb-1.5 block font-bold">
                  {t.reorder}
                </label>
                <input
                  id={`${id}-reorder`}
                  inputMode="decimal"
                  className={cn(input, "numeric")}
                  value={draft.reorderPoint}
                  aria-invalid={Boolean(errors.reorder)}
                  onChange={(event) => set("reorderPoint", event.target.value)}
                />
                <FieldError message={errors.reorder} />
              </div>
              <div>
                <label htmlFor={`${id}-tax`} className="mb-1.5 block font-bold">
                  {t.defaultTax}
                </label>
                <input
                  id={`${id}-tax`}
                  inputMode="decimal"
                  className={cn(input, "numeric")}
                  value={draft.taxPercent}
                  aria-invalid={Boolean(errors.tax)}
                  onChange={(event) => set("taxPercent", event.target.value)}
                />
                <FieldError message={errors.tax} />
              </div>
            </div>
          )}
        </div>
      </fieldset>
      <p className="text-muted-foreground">{t.locale(currency, cityOf(company.timezone))}</p>
      <FieldError message={errors.form} />
      {canEdit ? (
        <button
          type="submit"
          disabled={save.isPending}
          className="inline-flex min-h-[54px] items-center gap-2 self-start rounded-champ bg-primary px-5 font-bold text-primary-foreground outline-none hover:bg-primary/90 focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
        >
          {save.isPending && <Loader2 className="size-4 animate-spin" aria-hidden />}
          {t.save}
        </button>
      ) : (
        <p className="text-muted-foreground">{t.readOnly}</p>
      )}
    </form>
  );
}
