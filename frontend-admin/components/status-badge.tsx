import { Pill } from "@/components/ui";
import { STATUS_LABELS } from "@/lib/format";

const TONES = {
  active: "succes",
  suspended: "danger",
  trial: "attention",
} as const;

export function StatusBadge({ status }: { status: string }) {
  return (
    <Pill tone={TONES[status as keyof typeof TONES] ?? "neutre"}>
      {STATUS_LABELS[status] ?? status}
    </Pill>
  );
}
