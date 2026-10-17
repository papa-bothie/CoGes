/**
 * Où mène le lien « ← … » d'un écran d'action (ADR 0082) : là d'où l'on vient.
 *
 * Le lien qui ouvre l'écran passe son propre chemin en `?from=`. Ce chemin n'est suivi
 * que s'il reste sur CoGes (même règle que la destination après connexion, ADR 0049) ;
 * sinon, ou sans `from`, le lien ramène à l'écran parent. Le libellé nomme la page
 * visée : la personne, l'article ou la vente quand on vient de sa fiche, la rubrique
 * sinon.
 */

import { safePath } from "@/lib/auth/safe-next";
import { labels } from "@/lib/labels";
import { shortNumber } from "@/lib/money";

export type BackTarget = { href: string; label: string };

export type BackSubject = { kind: "customer" | "supplier" | "product" | "sale"; id: string };

/** Nom déjà connu d'une fiche (cache des lectures), ou `undefined`. */
export type NameOf = (subject: BackSubject) => string | undefined;

/** Origine fictive : seul compte qu'un chemin relatif ne quitte pas l'application. */
const ORIGIN = "https://coges.invalid";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const SECTIONS: Record<string, string> = {
  "/dashboard": labels.kit.nav.home,
  "/finance": labels.moneyScreens.title,
  "/products": labels.kit.nav.stock,
  "/inventory": labels.back.allMovements,
  "/customers": labels.kit.nav.clients,
  "/suppliers": labels.back.suppliers,
  "/insights": labels.kit.nav.advice,
  "/analytics": labels.kit.nav.advice,
  "/notifications": labels.kit.nav.alerts,
};

const SUBJECTS: Record<string, BackSubject["kind"]> = {
  customers: "customer",
  suppliers: "supplier",
  products: "product",
  sales: "sale",
};

function labelFor(pathname: string, nameOf: NameOf): string {
  const section = SECTIONS[pathname];
  if (section) return section;
  const [, collection, id, ...rest] = pathname.split("/");
  const kind = collection ? SUBJECTS[collection] : undefined;
  if (kind && id && UUID.test(id) && rest.length === 0) {
    const name = nameOf({ kind, id });
    if (kind === "sale") return labels.back.sale(shortNumber(name ?? null));
    return name ?? labels.back[kind];
  }
  return labels.back.generic;
}

export function resolveBack(
  from: string | null | undefined,
  fallback: BackTarget,
  nameOf: NameOf = () => undefined,
): BackTarget {
  const href = safePath(from, ORIGIN);
  if (!href) return fallback;
  const pathname = new URL(href, ORIGIN).pathname;
  return { href, label: labelFor(pathname, nameOf) };
}

/** `path` complété de `from=<origine>` : à mettre sur chaque lien qui ouvre un écran d'action. */
export function withFrom(path: string, from: string): string {
  const [base, query = ""] = path.split("?");
  const params = new URLSearchParams(query);
  params.set("from", from);
  return `${base}?${params.toString()}`;
}
