import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { BrandLogo } from "@/components/brand/brand";
import { LegalLinks } from "@/components/legal/legal-links";
import { vitrine } from "@/content/vitrine";
import { labels } from "@/lib/labels";
import { signupConfig } from "@/lib/signup/config";

import { SignupFlow } from "./signup-flow";

export const metadata: Metadata = { title: labels.signup.pageTitle };

/** Inscription fermée : la page n'existe pas (404), comme les routes de l'API. */
export const revalidate = 300;

/**
 * « Créer ma boutique » (lot 30, ADR 0118) : le formulaire, puis « Vérifiez votre e-mail »
 * ou « Demande reçue ». Rien ne passe par l'URL : tout reste en mémoire de l'onglet.
 */
export default async function SignupPage() {
  const config = await signupConfig();
  if (!config.enabled) notFound();
  return (
    <main className="flex min-h-dvh justify-center bg-background px-4 py-10">
      <div className="w-full max-w-[480px] space-y-6">
        <BrandLogo className="h-auto w-[200px]" />
        <SignupFlow
          instantWithEmail={config.instant_with_email}
          whatsapp={config.support_whatsapp || vitrine.whatsappNumber}
          supportHours={vitrine.supportHours}
          resendSeconds={config.resend_interval_seconds}
        />
        <LegalLinks />
      </div>
    </main>
  );
}
