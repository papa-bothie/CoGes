/**
 * PDF d'une pièce de vente (prompt 35, bloc T, ADR 0113) : téléchargé par l'API avec le jeton
 * dans l'en-tête (jamais dans une URL), puis enregistré ou partagé.
 *
 * Partager : l'API Web Share avec fichier (`navigator.share({ files })`) quand le téléphone la
 * prend en charge — WhatsApp, e-mail, etc. ; sinon le PDF est téléchargé et l'appelant ouvre
 * son repli (le lien WhatsApp avec le texte du reçu).
 */
import { toApiError } from "@/lib/api/errors";
import { attachmentName, saveBlob } from "@/lib/files";

export type SharedPdf = { blob: Blob; filename: string };
export type ShareOutcome = "shared" | "downloaded" | "cancelled";

/** Le PDF en `File`, sous le nom que le serveur lui donne (`Content-Disposition`). */
export function pdfFile({ blob, filename }: SharedPdf): File {
  return new File([blob], filename, { type: "application/pdf" });
}

/** Sait-on partager un PDF ici ? Vérifié au clic, avant tout `await` (fenêtres bloquées). */
export function canSharePdf(): boolean {
  if (typeof File === "undefined") return false;
  return canShareFile(new File([""], "piece.pdf", { type: "application/pdf" }));
}

/** Le téléphone sait-il partager ce fichier ? */
export function canShareFile(file: File): boolean {
  if (typeof navigator === "undefined" || typeof navigator.share !== "function") return false;
  try {
    return navigator.canShare?.({ files: [file] }) ?? false;
  } catch {
    return false;
  }
}

/**
 * Partage le PDF si possible, sinon le télécharge. Un partage annulé par la personne n'est
 * pas une erreur ; tout autre échec du partage retombe sur le téléchargement.
 */
export async function sharePdf(
  pdf: SharedPdf,
  { title, text }: { title: string; text?: string },
): Promise<ShareOutcome> {
  const file = pdfFile(pdf);
  if (canShareFile(file)) {
    try {
      await navigator.share({ files: [file], title, text });
      return "shared";
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return "cancelled";
    }
  }
  saveBlob(pdf.blob, pdf.filename);
  return "downloaded";
}

/** Lit un PDF de l'API en blob et garde le nom donné par le serveur. */
export async function pdfFromResponse(
  result: { data?: unknown; error?: unknown; response: Response },
  fallbackName: string,
): Promise<SharedPdf> {
  const { data, error, response } = result;
  if (!response.ok || !(data instanceof Blob)) throw toApiError(response.status, error);
  return {
    blob: data,
    filename: attachmentName(response.headers.get("Content-Disposition"), fallbackName),
  };
}
