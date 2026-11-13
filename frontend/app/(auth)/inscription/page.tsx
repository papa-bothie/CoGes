import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { EntreeLayout } from "@/components/auth/entree-layout";
import { LegalLinks } from "@/components/legal/legal-links";
import { vitrine } from "@/content/vitrine";
import { labels } from "@/lib/labels";
import { signupConfig } from "@/lib/signup/config";
import { ALWAYS_LIGHT_VIEWPORT } from "@/lib/theme/always-light";

import { SignupFlow } from "./signup-flow";

/** Toujours claire, quel que soit le thème (prompt 39, ADR 0123). */
export const viewport = ALWAYS_LIGHT_VIEWPORT;

export const metadata: Metadata = { title: labels.signup.pageTitle };

/** Inscription fermée : la page n'existe pas (404), comme les routes de l'API. */
export const revalidate = 300;

/**
 * « Créer ma boutique » (lot 30, ADR 0118) : le formulaire, puis « Vérifiez votre e-mail »
 * ou « Demande reçue ». Rien ne passe par l'URL : tout reste en mémoire de l'onglet. Même
 * mise en page que la connexion (`EntreeLayout`, prompt 39, bloc S).
 */
export default async function SignupPage() {
  const config = await signupConfig();
  if (!config.enabled) notFound();
  return (
    <EntreeLayout panel={labels.signup.panel}>
      <SignupFlow
        instantWithEmail={config.instant_with_email}
        whatsapp={config.support_whatsapp || vitrine.whatsappNumber}
        supportHours={vitrine.supportHours}
        resendSeconds={config.resend_interval_seconds}
      />
      <LegalLinks />
    </EntreeLayout>
  );
}
