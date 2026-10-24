import type { AuditEntry } from "@/lib/api/schema";

import { PAYMENT_METHOD_LABELS, PLATFORM_ROLE_LABELS, formatFcfa, shortName } from "./format";

const PLAN_NAMES: Record<string, string> = {
  starter: "Starter",
  business: "Business",
  premium: "Premium",
};
const SUBSCRIPTION_STATUS: Record<string, string> = {
  trial: "Essai",
  active: "Actif",
  past_due: "En retard",
  suspended: "Suspendu",
};

type Diff = Record<string, unknown>;

function part(diff: Diff, side: "before" | "after"): Diff {
  const value = diff[side];
  return value && typeof value === "object" ? (value as Diff) : {};
}

function role(value: unknown): string {
  return PLATFORM_ROLE_LABELS[String(value)] ?? String(value);
}

function withReason(sentence: string, diff: Diff): string {
  const reason = diff.reason;
  return typeof reason === "string" && reason ? `${sentence} — « ${reason} »` : sentence;
}

/**
 * Une ligne du journal en français (prompt 27, D4 d) : « Aïssatou D. a passé Moussa B. de
 * Support à Administrateur ». Jamais de JSON brut ; un cas inconnu reste lisible.
 */
export function describeEntry(entry: AuditEntry): string {
  const diff = (entry.diff ?? {}) as Diff;
  const before = part(diff, "before");
  const after = part(diff, "after");
  const actor = entry.actor_id ? shortName(entry.actor_name) : "CoGes (automatique)";
  const target = shortName(entry.entity_name);
  const company = entry.target_company_name ?? "une entreprise";

  switch (entry.entity_table) {
    case "platform_users": {
      if (entry.action === "login") return `${actor} s'est connecté`;
      if (entry.action === "insert") {
        if (!entry.actor_id)
          return `${target} a été créé en ligne de commande (${role(after.role)})`;
        return `${target} a rejoint l'équipe comme ${role(after.role)}`;
      }
      const sentences: string[] = [];
      if ("role" in after) {
        sentences.push(`${actor} a passé ${target} de ${role(before.role)} à ${role(after.role)}`);
      }
      if ("is_active" in after) {
        const verb = after.is_active ? "a réactivé" : "a suspendu";
        sentences.push(
          entry.actor_id
            ? `${actor} ${verb} ${target}`
            : `${target} a été ${after.is_active ? "réactivé" : "désactivé"} en ligne de commande`,
        );
      }
      return withReason(sentences.join(", et ") || `${actor} a modifié ${target}`, diff);
    }
    case "platform_invitations":
      if (entry.action === "insert") {
        return `${actor} a invité ${target} (${String(after.email ?? "")}) comme ${role(after.role)}`;
      }
      if (entry.action === "cancel") return `${actor} a annulé l'invitation de ${target}`;
      return `${actor} a renvoyé l'invitation de ${target}`;
    case "platform_auth_sessions":
      return `Les sessions de ${actor} ont été coupées : un ancien jeton a été réutilisé`;
    case "companies":
      return withReason(
        `${actor} a ${after.status === "suspended" ? "suspendu" : "réactivé"} ${company}`,
        diff,
      );
    case "subscriptions": {
      const sentences: string[] = [];
      if (after.plan && after.plan !== before.plan) {
        sentences.push(
          `${actor} a passé ${company} de ${PLAN_NAMES[String(before.plan)] ?? before.plan} à ${PLAN_NAMES[String(after.plan)] ?? after.plan}`,
        );
      }
      if (after.status && after.status !== before.status) {
        sentences.push(
          `${actor} a mis l'abonnement de ${company} en « ${SUBSCRIPTION_STATUS[String(after.status)] ?? after.status} »`,
        );
      }
      return withReason(
        sentences.join(", et ") || `${actor} a modifié l'abonnement de ${company}`,
        diff,
      );
    }
    case "subscription_payments": {
      const method = PAYMENT_METHOD_LABELS[String(after.method)] ?? String(after.method ?? "");
      return `${actor} a enregistré un paiement de ${formatFcfa(String(after.amount_fcfa ?? "0"))} (${method}) pour ${company}`;
    }
    case "support_sessions":
      if (entry.action === "insert") {
        const why = typeof after.justification === "string" ? ` — « ${after.justification} »` : "";
        return `${actor} a ouvert un accès support à ${company}${why}`;
      }
      if ("ended_at" in after) return `${actor} a fermé l'accès support à ${company}`;
      return `${actor} a repris son accès support à ${company}`;
    default:
      return `${actor} : ${entry.action} sur ${entry.entity_table}`;
  }
}

export const ACTION_LABELS: Record<string, string> = {
  insert: "Création",
  update: "Modification",
  cancel: "Annulation",
  login: "Connexion",
};
