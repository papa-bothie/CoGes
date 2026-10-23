import { STATUS_LABELS } from "@/lib/format";

const TONES: Record<string, string> = {
  active: "bg-succes-teinte text-succes",
  suspended: "bg-danger-teinte text-danger",
  trial: "bg-attention-teinte text-attention",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`rounded px-2 py-0.5 text-sm font-semibold ${TONES[status] ?? ""}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}
