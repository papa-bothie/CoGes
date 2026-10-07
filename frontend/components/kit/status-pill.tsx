import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

export type PillStatus = "paid" | "remaining" | "returned" | "cancelled" | "writtenOff";

const TONES: Record<PillStatus, string> = {
  paid: "bg-ventes-teinte text-ventes-encre",
  remaining: "bg-stock-teinte text-stock-encre",
  returned: "bg-argent-teinte text-argent-encre",
  cancelled: "bg-voile text-encre-2",
  // Écart noté dans maquette-v2/ecarts.md (lot 0) : même gris neutre qu'« Annulée ».
  writtenOff: "bg-voile text-encre-2",
};

/**
 * Pastille d'état de la maquette v2 : « Payé », « Reste 10 000 F », « Retour : 5 000 F »,
 * « Annulée ». `amount` est **déjà formaté** (`formatAmount`) pour « Reste » et « Retour ».
 */
export function StatusPill({
  status,
  amount,
  className,
}: {
  status: PillStatus;
  amount?: string;
  className?: string;
}) {
  const text =
    status === "remaining"
      ? labels.kit.status.remaining(amount ?? "")
      : status === "returned"
        ? labels.kit.status.returned(amount ?? "")
        : labels.kit.status[status];
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center rounded-full px-3 py-1.5 text-sm font-bold numeric",
        TONES[status],
        className,
      )}
    >
      {text}
    </span>
  );
}
