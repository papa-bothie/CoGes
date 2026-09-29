import Link from "next/link";

import { Button } from "@/components/ui/button";
import { labels } from "@/lib/labels";

export default function NotFound() {
  return (
    <main className="grid min-h-dvh place-items-center p-6">
      <div className="max-w-md text-center">
        <p className="text-sm font-medium text-muted-foreground">404</p>
        <h1 className="mt-2 text-2xl font-bold">{labels.errors.notFoundTitle}</h1>
        <p className="mt-2 text-muted-foreground">{labels.errors.notFoundBody}</p>
        <Button asChild className="mt-6">
          <Link href="/dashboard">{labels.errors.backToDashboard}</Link>
        </Button>
      </div>
    </main>
  );
}
