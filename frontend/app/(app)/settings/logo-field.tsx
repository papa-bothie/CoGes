"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ImageIcon, Loader2 } from "lucide-react";
import { useId, useRef, useState } from "react";
import { toast } from "sonner";

import { FieldError } from "@/components/field-error";
import { useCompanyLogo } from "@/hooks/use-company-logo";
import { ME_QUERY_KEY } from "@/hooks/use-me";
import { api } from "@/lib/api/client";
import { errorMessage, toApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/queries/keys";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

const t = labels.settingsScreens.shop.logo;

/** Même règle que le serveur (ADR 0111) : il revérifie le vrai type dans le contenu. */
export const LOGO_TYPES = ["image/png", "image/jpeg", "image/webp"] as const;
export const LOGO_MAX_BYTES = 2 * 1024 * 1024;

/** Ce qui refuse un fichier avant tout envoi, ou `null`. */
export function logoRefusal(file: Pick<File, "size" | "type">): string | null {
  if (!(LOGO_TYPES as readonly string[]).includes(file.type)) return t.unsupported;
  if (file.size > LOGO_MAX_BYTES) return t.tooLarge;
  return null;
}

const button =
  "inline-flex min-h-cible items-center gap-2 rounded-champ px-4 font-bold outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50";

/**
 * Logo de la boutique (prompt 35, bloc L) : aperçu, puis « Ajouter le logo », « Changer »,
 * « Retirer » pour qui a `company:update`. Enregistré tout de suite, hors du formulaire.
 */
export function LogoField({
  version,
  canEdit,
}: {
  version: string | null | undefined;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();
  const url = useCompanyLogo(version);
  const input = useRef<HTMLInputElement>(null);
  const id = useId();
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.company });
    void queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
  };

  const upload = useMutation({
    meta: { toastError: false },
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append("file", file);
      const { error: failure, response } = await api.PUT("/api/v1/companies/me/logo", {
        body: body as never,
        bodySerializer: (value: unknown) => value as FormData,
      });
      if (!response.ok) throw toApiError(response.status, failure);
    },
    onSuccess: () => {
      setError(null);
      refresh();
      toast.success(t.saved);
    },
    onError: (failure) => setError(errorMessage(failure)),
  });

  const remove = useMutation({
    meta: { toastError: false },
    mutationFn: async () => {
      const { error: failure, response } = await api.DELETE("/api/v1/companies/me/logo");
      if (!response.ok) throw toApiError(response.status, failure);
    },
    onSuccess: () => {
      setError(null);
      refresh();
      toast.success(t.removed);
    },
    onError: (failure) => setError(errorMessage(failure)),
  });

  const choose = (file: File | undefined) => {
    if (input.current) input.current.value = "";
    if (!file) return;
    const refusal = logoRefusal(file);
    setError(refusal);
    if (!refusal) upload.mutate(file);
  };

  const busy = upload.isPending || remove.isPending;
  const hasLogo = Boolean(version);

  return (
    <section aria-labelledby={`${id}-title`} className="flex flex-col gap-2">
      <h3 id={`${id}-title`} className="font-bold">
        {t.title}
      </h3>
      <div className="flex flex-wrap items-center gap-4">
        <div
          className={cn(
            "flex size-24 shrink-0 items-center justify-center overflow-hidden rounded-champ border border-filet bg-card",
          )}
        >
          {url ? (
            // eslint-disable-next-line @next/next/no-img-element -- adresse data: locale
            <img src={url} alt={t.preview} className="max-h-full max-w-full object-contain" />
          ) : (
            <ImageIcon aria-hidden className="size-8 text-muted-foreground" />
          )}
        </div>
        <div className="flex flex-col gap-2">
          {!hasLogo && <p className="text-muted-foreground">{t.none}</p>}
          {canEdit ? (
            <div className="flex flex-wrap gap-2">
              <input
                ref={input}
                id={`${id}-file`}
                type="file"
                accept={LOGO_TYPES.join(",")}
                className="sr-only"
                tabIndex={-1}
                aria-hidden
                onChange={(event) => choose(event.target.files?.[0])}
              />
              <button
                type="button"
                disabled={busy}
                onClick={() => input.current?.click()}
                className={cn(button, "bg-primary text-primary-foreground hover:bg-primary/90")}
              >
                {upload.isPending && <Loader2 className="size-4 animate-spin" aria-hidden />}
                {hasLogo ? t.change : t.add}
              </button>
              {hasLogo && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => remove.mutate()}
                  className={cn(button, "border border-filet hover:bg-voile")}
                >
                  {remove.isPending && <Loader2 className="size-4 animate-spin" aria-hidden />}
                  {t.remove}
                </button>
              )}
            </div>
          ) : null}
          <p className="text-sm text-muted-foreground">{t.hint}</p>
        </div>
      </div>
      <FieldError message={error ?? undefined} />
    </section>
  );
}
