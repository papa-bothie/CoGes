import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { BrandLogo } from "@/components/brand/brand";
import { labels } from "@/lib/labels";
import { signupConfig } from "@/lib/signup/config";

import { VerifyLink } from "../verify-link";

export const metadata: Metadata = {
  title: labels.signup.verifyingTitle,
  // Le jeton est dans l'adresse : aucune page suivante ne doit le recevoir en `Referer`.
  referrer: "no-referrer",
};

/** Lien de l'e-mail de vérification (ADR 0118). Inscription fermée : 404. */
export default async function VerificationPage({ params }: { params: Promise<{ jeton: string }> }) {
  const config = await signupConfig();
  if (!config.enabled) notFound();
  const { jeton } = await params;
  return (
    <main className="flex min-h-dvh justify-center bg-background px-4 py-10">
      <div className="w-full max-w-[480px] space-y-6">
        <BrandLogo className="h-auto w-[200px]" />
        <VerifyLink token={jeton} />
      </div>
    </main>
  );
}
