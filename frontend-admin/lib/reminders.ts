import type { ReminderItem } from "@/lib/api/schema";

export type { ReminderItem };

/** L'étape, en mots et en couleur (orange au dernier rappel, rouge une fois en pause). */
export const STAGES: Record<
  ReminderItem["stage"],
  { label: string; tone: "info" | "attention" | "danger" }
> = {
  eve: { label: "Veille", tone: "info" },
  due: { label: "Jour J (grâce)", tone: "info" },
  last: { label: "Dernier rappel", tone: "attention" },
  suspended: { label: "En pause", tone: "danger" },
};

export function kindLabel(item: Pick<ReminderItem, "kind" | "plan_name">): string {
  return item.kind === "trial" ? "Essai gratuit" : `Abonnement ${item.plan_name}`;
}

/** Ce que la tâche de nuit a déjà envoyé pour cette échéance. */
export function sentLabel(item: Pick<ReminderItem, "sent_stage">): string {
  return item.sent_stage
    ? `Déjà envoyé : ${STAGES[item.sent_stage].label.toLowerCase()}`
    : "Rien d'envoyé encore";
}
