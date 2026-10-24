import type { Metadata } from "next";

import { BrandLogo } from "@/components/brand/brand";
import { labels } from "@/lib/labels";

export const metadata: Metadata = { title: labels.support.endedTitle };

/** Fin de l'accès support (ADR 0092) : fermée par l'équipe, ou son heure est passée. */
export default function SupportEndedPage() {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-[440px] space-y-6">
        <BrandLogo className="h-auto w-[220px]" />
        <h1 className="text-[28px] leading-tight font-extrabold">{labels.support.endedTitle}</h1>
        <p className="text-lg text-encre-2">{labels.support.endedBody}</p>
      </div>
    </main>
  );
}
