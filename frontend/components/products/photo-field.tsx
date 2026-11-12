"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, ImageIcon, ImagePlus, Loader2 } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { toast } from "sonner";

import { FieldError } from "@/components/field-error";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage, toApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/queries/keys";
import { labels } from "@/lib/labels";
import { photoUrl, shrinkForUpload, type ProductPhoto } from "@/lib/photo";
import { cn } from "@/lib/utils";

const t = labels.photo;

export const PHOTO_TYPES = ["image/jpeg", "image/png", "image/webp"] as const;
export const PHOTO_MAX_BYTES = 5 * 1024 * 1024;

/** Les photos sont-elles disponibles ? Sans compte Cloudinary, aucun bouton (ADR 0121). */
export function usePhotosEnabled(enabled = true): boolean {
  const config = useQuery({
    queryKey: [...queryKeys.products.all, "photos-config"],
    queryFn: () => unwrap(api.GET("/api/v1/products/photos/config")),
    staleTime: 60 * 60 * 1000,
    enabled,
  });
  return config.data?.enabled ?? false;
}

/** Refus lisible avant tout envoi ; le serveur revérifie dans le contenu. */
export function photoRefusal(file: Pick<File, "size" | "type">): string | null {
  if (file.type && !(PHOTO_TYPES as readonly string[]).includes(file.type)) return t.unsupported;
  if (file.size > PHOTO_MAX_BYTES * 4) return t.tooLarge;
  return null;
}

/** Dépose la photo d'un article déjà créé (`PUT /products/{id}/photo`). */
export async function uploadProductPhoto(productId: string, file: File): Promise<void> {
  const body = new FormData();
  body.append("file", await shrinkForUpload(file), "photo.jpg");
  const { error: failure, response } = await api.PUT("/api/v1/products/{product_id}/photo", {
    params: { path: { product_id: productId } },
    body: body as never,
    bodySerializer: (value: unknown) => value as FormData,
  });
  if (!response.ok) throw toApiError(response.status, failure);
}

const button =
  "inline-flex min-h-cible items-center gap-2 rounded-champ px-4 font-bold outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50";

/**
 * Photo d'un article (prompt 36, bloc I, ADR 0121) : « Prendre une photo » (caméra arrière),
 * « Choisir une image », aperçu et « Retirer ».
 *
 * Avec `productId`, chaque geste part tout de suite (fiche, modification). Sans, la photo
 * choisie est gardée par `onPending` et partira à l'enregistrement de l'article (« Nouvel
 * article »).
 */
export function PhotoField({
  name,
  photo,
  productId,
  onPending,
}: {
  name: string;
  photo?: ProductPhoto | null;
  productId?: string;
  onPending?: (file: File | null) => void;
}) {
  const queryClient = useQueryClient();
  const id = useId();
  const camera = useRef<HTMLInputElement>(null);
  const library = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<File | null>(null);
  const [localUrl, setLocalUrl] = useState<string | null>(null);

  // L'aperçu local est libéré quand il change et quand le champ disparaît.
  const previewRef = useRef<string | null>(null);
  const showLocal = (file: File | null) => {
    if (previewRef.current) URL.revokeObjectURL(previewRef.current);
    previewRef.current = file ? URL.createObjectURL(file) : null;
    setLocalUrl(previewRef.current);
  };
  useEffect(
    () => () => {
      if (previewRef.current) URL.revokeObjectURL(previewRef.current);
    },
    [],
  );

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.products.all });
    void queryClient.invalidateQueries({ queryKey: queryKeys.stock.all });
  };

  const upload = useMutation({
    meta: { toastError: false },
    mutationFn: (file: File) => uploadProductPhoto(productId!, file),
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
      const { error: failure, response } = await api.DELETE("/api/v1/products/{product_id}/photo", {
        params: { path: { product_id: productId! } },
      });
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
    if (camera.current) camera.current.value = "";
    if (library.current) library.current.value = "";
    if (!file) return;
    const refusal = photoRefusal(file);
    setError(refusal);
    if (refusal) return;
    if (productId) {
      upload.mutate(file);
    } else {
      setPending(file);
      showLocal(file);
      onPending?.(file);
    }
  };

  const clearPending = () => {
    setPending(null);
    showLocal(null);
    onPending?.(null);
  };

  const busy = upload.isPending || remove.isPending;
  const shown = pending ? localUrl : photo ? photoUrl(photo, 384, "carre") : null;
  const has = Boolean(pending || photo);

  return (
    <section aria-labelledby={`${id}-title`} className="flex flex-col gap-2">
      <h2 id={`${id}-title`} className="font-bold">
        {t.title}
      </h2>
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex size-24 shrink-0 items-center justify-center overflow-hidden rounded-champ border border-filet bg-card">
          {shown ? (
            // eslint-disable-next-line @next/next/no-img-element -- aperçu local ou image Cloudinary
            <img
              src={shown}
              alt={t.preview(name || "l'article")}
              className="size-full object-cover"
            />
          ) : (
            <ImageIcon aria-hidden className="size-8 text-muted-foreground" />
          )}
        </div>
        <div className="flex min-w-0 flex-[1_1_220px] flex-col gap-2">
          {!has && <p className="text-muted-foreground">{t.none}</p>}
          {pending && <p className="text-muted-foreground">{t.pending}</p>}
          <div className="flex flex-wrap gap-2">
            <input
              ref={camera}
              type="file"
              accept={PHOTO_TYPES.join(",")}
              capture="environment"
              className="sr-only"
              tabIndex={-1}
              aria-hidden
              data-testid="photo-camera"
              onChange={(event) => choose(event.target.files?.[0])}
            />
            <input
              ref={library}
              type="file"
              accept={PHOTO_TYPES.join(",")}
              className="sr-only"
              tabIndex={-1}
              aria-hidden
              data-testid="photo-library"
              onChange={(event) => choose(event.target.files?.[0])}
            />
            <button
              type="button"
              disabled={busy}
              onClick={() => camera.current?.click()}
              className={cn(button, "bg-primary text-primary-foreground hover:bg-primary/90")}
            >
              {upload.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Camera className="size-5" aria-hidden />
              )}
              {has ? t.change : t.take}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => library.current?.click()}
              className={cn(button, "border border-filet hover:bg-voile")}
            >
              <ImagePlus className="size-5" aria-hidden />
              {t.choose}
            </button>
            {has && (
              <button
                type="button"
                disabled={busy}
                onClick={() => (pending ? clearPending() : remove.mutate())}
                className={cn(button, "border border-filet hover:bg-voile")}
              >
                {remove.isPending && <Loader2 className="size-4 animate-spin" aria-hidden />}
                {t.remove}
              </button>
            )}
          </div>
          <p className="text-sm text-muted-foreground">{t.hint}</p>
          <FieldError message={error} />
        </div>
      </div>
    </section>
  );
}
