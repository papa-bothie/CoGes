import type { SecurityEvent } from "@/lib/api/schema";
import { formatDateTime } from "@/lib/format";

/**
 * Signaux de sécurité de l'équipe (ADR 0105), en phrases pour « À traiter ». Aucun ne
 * porte de secret : qui, quoi, depuis quel navigateur, quand.
 */
export function securityEventText(event: SecurityEvent): string {
  const when = formatDateTime(event.occurred_at);
  switch (event.kind) {
    case "new_device":
      return `${event.display_name} s'est connecté depuis un nouvel appareil (${event.device ?? "navigateur inconnu"}) le ${when}`;
    case "recovery_code_used":
      return `${event.display_name} a utilisé un code de secours le ${when}`;
    case "mfa_enabled":
      return `${event.display_name} a activé sa double authentification le ${when}`;
    case "mfa_reset":
      return `La double authentification de ${event.display_name} a été réinitialisée le ${when}`;
  }
}

/** Un code de secours utilisé ou une réinitialisation se vérifient en priorité. */
export function securityEventTone(event: SecurityEvent): "danger" | "attention" {
  return event.kind === "recovery_code_used" || event.kind === "mfa_reset" ? "danger" : "attention";
}
