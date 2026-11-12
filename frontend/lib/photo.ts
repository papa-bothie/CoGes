import type { Schemas } from "@/lib/api/schema";

export type ProductPhoto = Schemas["ProductPhoto"];

/** Hôte des images, seul ajouté à `img-src` (next.config.ts, ADR 0121). */
export const PHOTO_HOST = "https://res.cloudinary.com";

/**
 * Adresse d'une photo d'article chez Cloudinary, à la taille demandée (ADR 0121) : format et
 * qualité choisis par Cloudinary pour l'appareil (`f_auto,q_auto`), largeur adaptée. Carrée
 * et recadrée pour une vignette, entière pour la fiche. Rien d'autre que des chiffres et
 * l'identifiant rendu par le serveur n'entre dans l'adresse.
 */
export function photoUrl(
  photo: ProductPhoto,
  pixels: number,
  shape: "carre" | "entiere" = "carre",
): string {
  const size = Math.max(16, Math.min(1600, Math.round(pixels)));
  const transform =
    shape === "carre"
      ? `f_auto,q_auto,c_fill,g_auto,w_${size},h_${size}`
      : `f_auto,q_auto,c_limit,w_${size}`;
  const cloud = encodeURIComponent(photo.cloud_name);
  const id = photo.public_id.split("/").map(encodeURIComponent).join("/");
  return `${PHOTO_HOST}/${cloud}/image/upload/${transform}/v${photo.version}/${id}`;
}

/** Côté visé avant l'envoi : celui que le serveur garde (ADR 0121). */
const SEND_SIDE = 1600;

/**
 * Réduit la photo du téléphone à 1600 px en JPEG avant l'envoi : moins de données sur un
 * réseau lent, et jamais au-delà des 5 Mo permis. Le serveur ré-encode quand même. Sans
 * `createImageBitmap` (ancien navigateur), le fichier part tel quel.
 */
export async function shrinkForUpload(file: File): Promise<Blob> {
  if (typeof createImageBitmap !== "function" || typeof document === "undefined") return file;
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const scale = Math.min(1, SEND_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const context = canvas.getContext("2d");
    if (!context) return file;
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", 0.9),
    );
    return blob && blob.size < file.size ? blob : file;
  } catch {
    return file;
  }
}
