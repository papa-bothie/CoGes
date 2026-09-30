import type { LucideIcon } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

// L'icône accompagne le libellé ; seule une alerte ou un danger la colore (un état, pas une
// décoration). La teinte exacte des états relève de la passe « colorize ».
const TONES = {
  primary: "text-muted-foreground",
  success: "text-muted-foreground",
  warning: "text-warning",
  danger: "text-destructive",
  neutral: "text-muted-foreground",
} as const;

/**
 * Carte d'indicateur. `value` arrive **déjà formatée** (`formatMoney`…) : la carte ne
 * calcule rien.
 */
export function KpiCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = "primary",
  loading = false,
}: {
  label: string;
  value: string;
  hint?: string;
  icon: LucideIcon;
  tone?: keyof typeof TONES;
  loading?: boolean;
}) {
  return (
    <Card className="gap-1 px-4 py-4">
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Icon className={cn("size-4 shrink-0", TONES[tone])} aria-hidden />
        {label}
      </p>
      {loading ? <Skeleton className="h-8 w-32" /> : <p className="text-figure numeric">{value}</p>}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </Card>
  );
}
