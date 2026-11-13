import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { EntreeLayout } from "@/components/auth/entree-layout";
import { LegalLinks } from "@/components/legal/legal-links";
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
    <EntreeLayout panel={labels.signup.panel}>
      <VerifyLink token={jeton} />
      <LegalLinks />
    </EntreeLayout>
  );
}
