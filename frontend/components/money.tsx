import { formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Montant tel que l'API l'a renvoyé, formaté sans passer par un `float` : chiffres
 * tabulaires et **jamais** coupé sur deux lignes (défaut du prototype, § 5).
 */
export function Money({
  value,
  currency,
  className,
}: {
  value: string | null | undefined;
  currency?: string;
  className?: string;
}) {
  return (
    <span className={cn("numeric whitespace-nowrap", className)}>
      {formatMoney(value, currency)}
    </span>
  );
}
