import type { Metadata } from "next";

import { BrandLogo } from "@/components/brand/brand";
import { labels } from "@/lib/labels";

import { SupportEntry } from "./support-entry";

export const metadata: Metadata = { title: labels.support.opening };

/** Entrée de l'accès support (ADR 0092) : le jeton arrive dans le fragment de l'adresse. */
export default function SupportPage() {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-[440px] space-y-6">
        <BrandLogo className="h-auto w-[220px]" />
        <SupportEntry />
      </div>
    </main>
  );
}
