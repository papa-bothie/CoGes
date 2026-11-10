import type { Metadata } from "next";

import { BrandLogo } from "@/components/brand/brand";
import { labels } from "@/lib/labels";

import { AcceptanceForm } from "./acceptance-form";

export const metadata: Metadata = { title: labels.legal.acceptance.pageTitle };

const t = labels.legal.acceptance;

/**
 * « Avant de continuer » (prompt 36, ADR 0117) : tant que la version courante des textes
 * légaux n'est pas acceptée, la coquille renvoie ici et le serveur refuse tout le reste
 * (409 `legal_acceptance_required`). Après « Choisissez votre mot de passe » s'il y a lieu.
 */
export default function AcceptancePage() {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-[480px] space-y-6">
        <BrandLogo className="h-auto w-[220px]" />
        <h1 className="text-[32px] leading-tight font-extrabold">{t.pageTitle}</h1>
        <p className="text-lg text-encre-2">{t.intro}</p>
        <AcceptanceForm />
      </div>
    </main>
  );
}
