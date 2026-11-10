import type { SignupRequestRead } from "@/lib/api/schema";

/** Raisons d'un refus, en liste fermée (ADR 0118), avec leur phrase. */
export const REJECT_REASONS: {
  value: SignupRequestRead["reject_reason"] & string;
  label: string;
}[] = [
  { value: "unreachable", label: "Injoignable" },
  { value: "duplicate", label: "Déjà client (doublon)" },
  { value: "not_a_business", label: "Pas un commerce" },
  { value: "fraud", label: "Fraude ou abus" },
  { value: "other", label: "Autre raison" },
];

export function rejectLabel(reason: string | null | undefined): string {
  return REJECT_REASONS.find((item) => item.value === reason)?.label ?? "—";
}

/** Où en est la demande, en mots. */
export function requestState(request: SignupRequestRead): {
  label: string;
  tone: "succes" | "danger" | "attention" | "info" | "neutre";
} {
  if (request.status === "activated") return { label: "Boutique ouverte", tone: "succes" };
  if (request.status === "rejected") return { label: "Refusée", tone: "danger" };
  if (request.status === "abandoned") return { label: "Abandonnée", tone: "neutre" };
  if (request.path === "team") return { label: "À traiter par l'équipe", tone: "attention" };
  return { label: "Lien e-mail en attente", tone: "info" };
}

/** « 3 h », « 2 j » : ancienneté d'une demande, au plus juste. */
export function age(createdAt: string, now: Date = new Date()): string {
  const hours = Math.max(
    0,
    Math.floor((now.getTime() - new Date(createdAt).getTime()) / 3_600_000),
  );
  if (hours < 1) return "moins d'1 h";
  if (hours < 48) return `${hours} h`;
  return `${Math.floor(hours / 24)} j`;
}

/** Chiffres du numéro pour `wa.me` et `tel:` : « +221770000000 » → « 221770000000 ». */
export function phoneDigits(phone: string | null | undefined): string {
  return (phone ?? "").replace(/\D/g, "");
}

/** Premier message à un commerçant sans e-mail : modifiable avant l'envoi. */
export function firstContactMessage(request: SignupRequestRead): string {
  const name = request.full_name?.split(" ")[0] ?? "";
  return (
    `Bonjour ${name}, ici l'équipe CoGes. Vous avez demandé à ouvrir « ${request.shop_name ?? ""} ». ` +
    "Nous ouvrons votre boutique avec vous : êtes-vous disponible quelques minutes ?"
  );
}

/** L'accès, une fois la boutique ouverte : le code et le lien, JAMAIS le mot de passe. */
export function accessMessage(slug: string, merchantUrl: string): string {
  const login = `${merchantUrl.replace(/\/+$/, "")}/login?boutique=${encodeURIComponent(slug)}`;
  return (
    `Votre boutique CoGes est ouverte. Code de la boutique : ${slug}. ` +
    `Connectez-vous ici avec votre numéro et le mot de passe que vous avez choisi : ${login}`
  );
}

export function whatsappLink(phone: string | null | undefined, message: string): string {
  return `https://wa.me/${phoneDigits(phone)}?text=${encodeURIComponent(message)}`;
}
