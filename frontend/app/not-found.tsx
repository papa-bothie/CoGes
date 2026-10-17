import { SearchX } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { labels } from "@/lib/labels";

/** Même ton et même mise en page que l'écran d'incident (ADR 0085). */
export default function NotFound() {
  return (
    <main className="grid min-h-dvh place-items-center bg-background p-6">
      <div className="flex max-w-md flex-col items-center gap-4 text-center">
        <span className="grid size-16 place-items-center rounded-full bg-muted text-muted-foreground">
          <SearchX className="size-8" aria-hidden />
        </span>
        <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">
          {labels.errors.notFoundTitle}
        </h1>
        <p className="text-lg text-muted-foreground">{labels.errors.notFoundBody}</p>
        <Button asChild>
          <Link href="/dashboard">{labels.incident.home}</Link>
        </Button>
      </div>
    </main>
  );
}
