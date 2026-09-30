"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ME_QUERY_KEY } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { parseDecimalInput, toInputDecimal } from "@/lib/decimal";
import { labels } from "@/lib/labels";

type Company = Schemas["CompanyRead"];

/** Fuseaux proposés : l'Afrique d'abord (cible du produit), puis UTC et Paris. */
function timeZones(current: string): string[] {
  const all =
    typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [];
  const zones = all.filter((zone) => zone.startsWith("Africa/"));
  return [...new Set([current, ...zones, "UTC", "Europe/Paris"])];
}

type Draft = {
  name: string;
  timezone: string;
  taxEnabled: boolean;
  intelligenceEnabled: boolean;
  reorderPoint: string;
};

function draftOf(company: Company): Draft {
  const settings = company.settings as Record<string, unknown>;
  const reorder = settings.default_reorder_point;
  return {
    name: company.name,
    timezone: company.timezone,
    // Absent vaut « activé » (ADR 0022, 0036) : l'écran affiche le comportement réel.
    taxEnabled: settings.tax_enabled !== false,
    intelligenceEnabled: settings.intelligence_enabled !== false,
    reorderPoint: typeof reorder === "string" ? toInputDecimal(reorder) : "",
  };
}

/** Entreprise : identité et règles de gestion. Les réglages sensibles demandent confirmation. */
export function CompanyTab() {
  const query = useQuery({
    queryKey: queryKeys.company,
    queryFn: () => unwrap(api.GET("/api/v1/companies/me")),
  });
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (!query.data) return <Skeleton className="h-96 w-full" />;
  return <CompanyForm key={query.data.updated_at} company={query.data} />;
}

function CompanyForm({ company }: { company: Company }) {
  const queryClient = useQueryClient();
  const canEdit = usePermission("company:update");
  const initial = draftOf(company);
  const [draft, setDraft] = useState<Draft>(initial);
  const [confirming, setConfirming] = useState<string[] | null>(null);
  const [errors, setErrors] = useState<{ name?: string; reorder?: string; form?: string }>({});
  const t = labels.settings.company;
  const onOff = (value: boolean) => (value ? t.on : t.off);

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
      setConfirming(null);
      toast.success(t.saved);
    },
    onError: (error) => {
      setConfirming(null);
      setErrors({ form: errorMessage(error) });
    },
  });

  const reorder = draft.reorderPoint.trim() ? parseDecimalInput(draft.reorderPoint) : null;

  const buildBody = (): Schemas["CompanyUpdate"] => {
    const body: Schemas["CompanyUpdate"] = {};
    if (draft.name.trim() !== company.name) body.name = draft.name.trim();
    if (draft.timezone !== company.timezone) body.timezone = draft.timezone;
    const settingsChanged =
      draft.taxEnabled !== initial.taxEnabled ||
      draft.intelligenceEnabled !== initial.intelligenceEnabled ||
      draft.reorderPoint.trim() !== initial.reorderPoint;
    if (settingsChanged) {
      // `settings` remplace l'objet entier (ADR 0054) : on renvoie les autres clés.
      body.settings = {
        ...company.settings,
        tax_enabled: draft.taxEnabled,
        intelligence_enabled: draft.intelligenceEnabled,
        default_reorder_point: reorder,
      };
    }
    return body;
  };

  const sensitiveChanges = (): string[] => {
    const changes: string[] = [];
    if (draft.timezone !== company.timezone)
      changes.push(t.change(t.timezone, company.timezone, draft.timezone));
    if (draft.taxEnabled !== initial.taxEnabled)
      changes.push(t.change(t.taxEnabled, onOff(initial.taxEnabled), onOff(draft.taxEnabled)));
    if (draft.intelligenceEnabled !== initial.intelligenceEnabled)
      changes.push(
        t.change(
          t.intelligenceEnabled,
          onOff(initial.intelligenceEnabled),
          onOff(draft.intelligenceEnabled),
        ),
      );
    if (draft.reorderPoint.trim() !== initial.reorderPoint)
      changes.push(
        t.change(
          t.reorderPoint,
          initial.reorderPoint || t.none,
          draft.reorderPoint.trim() || t.none,
        ),
      );
    return changes;
  };

  const submit = () => {
    const next: typeof errors = {};
    if (!draft.name.trim()) next.name = labels.validation.required;
    if (draft.reorderPoint.trim() && (reorder === null || !/^\d+(\.\d{1,3})?$/.test(reorder)))
      next.reorder = t.invalidThreshold;
    setErrors(next);
    if (Object.keys(next).length > 0) return;
    const body = buildBody();
    if (Object.keys(body).length === 0) return;
    const sensitive = sensitiveChanges();
    if (sensitive.length > 0) setConfirming(sensitive);
    else save.mutate(body);
  };

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  return (
    <form
      className="grid gap-4 xl:grid-cols-2"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <Card>
        <CardHeader>
          <CardTitle>{t.identity}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="company-name">{t.name}</Label>
            <Input
              id="company-name"
              value={draft.name}
              maxLength={200}
              disabled={!canEdit}
              aria-invalid={Boolean(errors.name)}
              onChange={(event) => set("name", event.target.value)}
              className="h-9"
            />
            <FieldError message={errors.name} />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="company-slug">{t.slug}</Label>
              <Input id="company-slug" value={company.slug} readOnly disabled className="h-9" />
              <p className="text-xs text-muted-foreground">{t.slugHint}</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="company-currency">{t.currency}</Label>
              <Input
                id="company-currency"
                value={company.currency}
                readOnly
                disabled
                className="h-9"
              />
              <p className="text-xs text-muted-foreground">{t.currencyHint}</p>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="company-timezone">{t.timezone}</Label>
            <Select
              value={draft.timezone}
              disabled={!canEdit}
              onValueChange={(value) => set("timezone", value)}
            >
              <SelectTrigger id="company-timezone" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {timeZones(company.timezone).map((zone) => (
                  <SelectItem key={zone} value={zone}>
                    {zone}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">{t.timezoneHint}</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t.rules}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          {(
            [
              ["taxEnabled", t.taxEnabled, t.taxHint],
              ["intelligenceEnabled", t.intelligenceEnabled, t.intelligenceHint],
            ] as const
          ).map(([key, label, hint]) => (
            <label key={key} className="flex items-start gap-3">
              <input
                type="checkbox"
                className="mt-0.5 size-4 accent-primary"
                checked={draft[key]}
                disabled={!canEdit}
                onChange={(event) => set(key, event.target.checked)}
              />
              <span>
                <span className="block text-sm font-medium">{label}</span>
                <span className="block text-xs text-muted-foreground">{hint}</span>
              </span>
            </label>
          ))}
          <div className="space-y-1.5">
            <Label htmlFor="company-reorder">{t.reorderPoint}</Label>
            <Input
              id="company-reorder"
              inputMode="decimal"
              value={draft.reorderPoint}
              disabled={!canEdit}
              aria-invalid={Boolean(errors.reorder)}
              onChange={(event) => set("reorderPoint", event.target.value)}
              className="h-9 w-40 text-right numeric"
            />
            <FieldError message={errors.reorder} />
            <p className="text-xs text-muted-foreground">{t.reorderHint}</p>
          </div>
        </CardContent>
      </Card>

      <div className="flex items-center justify-end gap-3 xl:col-span-2">
        <FieldError message={errors.form} />
        {canEdit ? (
          <Button type="submit" disabled={save.isPending}>
            {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
            {t.save}
          </Button>
        ) : (
          <p className="text-sm text-muted-foreground">{t.readOnly}</p>
        )}
      </div>

      <Dialog open={confirming !== null} onOpenChange={(open) => !open && setConfirming(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t.confirmTitle}</DialogTitle>
            <DialogDescription>{t.confirmBody}</DialogDescription>
          </DialogHeader>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {confirming?.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setConfirming(null)}>
              {labels.common.cancel}
            </Button>
            <Button
              type="button"
              disabled={save.isPending}
              onClick={() => save.mutate(buildBody())}
            >
              {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t.confirmSubmit}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </form>
  );
}
