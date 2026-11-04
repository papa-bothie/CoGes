"use client";

import { useMutation } from "@tanstack/react-query";
import { Download, Loader2, Share2 } from "lucide-react";
import { toast } from "sonner";

import { errorMessage } from "@/lib/api/errors";
import { saveBlob } from "@/lib/files";
import { labels } from "@/lib/labels";
import { canSharePdf, sharePdf, type SharedPdf } from "@/lib/pdf-share";
import { cn } from "@/lib/utils";

const t = labels.receipt.pdf;

/**
 * « Télécharger le PDF » et « Partager » d'une pièce de vente (prompt 35, bloc T, ADR 0113).
 *
 * `fallback` (le lien WhatsApp avec le texte du reçu) s'ouvre **au clic** quand le
 * téléphone ne sait pas partager un fichier : ouvert après un `await`, il serait bloqué.
 */
export function PdfActions({
  load,
  title,
  shareText,
  fallback,
  className,
}: {
  load: () => Promise<SharedPdf>;
  title: string;
  shareText?: string;
  fallback?: string;
  className: string;
}) {
  const download = useMutation({
    meta: { toastError: false },
    mutationFn: async () => {
      const pdf = await load();
      saveBlob(pdf.blob, pdf.filename);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const share = useMutation({
    meta: { toastError: false },
    mutationFn: async () => sharePdf(await load(), { title, text: shareText }),
    onSuccess: (outcome) => {
      if (outcome === "downloaded") toast.success(t.downloaded);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const onShare = () => {
    if (!canSharePdf() && fallback) window.open(fallback, "_blank", "noopener,noreferrer");
    share.mutate();
  };
  const busy = download.isPending || share.isPending;

  return (
    <>
      <button type="button" disabled={busy} onClick={() => download.mutate()} className={className}>
        {download.isPending ? (
          <Loader2 className="size-[22px] animate-spin" aria-hidden />
        ) : (
          <Download className="size-[22px]" aria-hidden />
        )}
        {t.download}
      </button>
      <button type="button" disabled={busy} onClick={onShare} className={cn(className)}>
        {share.isPending ? (
          <Loader2 className="size-[22px] animate-spin" aria-hidden />
        ) : (
          <Share2 className="size-[22px]" aria-hidden />
        )}
        {t.share}
      </button>
    </>
  );
}
