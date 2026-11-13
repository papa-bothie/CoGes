import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { EntreeLayout } from "@/components/auth/entree-layout";
import { LegalLinks } from "@/components/legal/legal-links";
import { labels } from "@/lib/labels";
import { signupConfig } from "@/lib/signup/config";
import { ALWAYS_LIGHT_VIEWPORT } from "@/lib/theme/always-light";

import { VerifyLink } from "./verify-link";

/** Toujours claire, quel que soit le thème (prompt 39, ADR 0123). */
export const viewport = ALWAYS_LIGHT_VIEWPORT;

export const metadata: Metadata = { title: labels.signup.invalidTitle };

/** Adresse sans jeton : celle qui reste après lecture du lien, ou rechargée. */
export default async function VerificationWithoutToken() {
  const config = await signupConfig();
  if (!config.enabled) notFound();
  return (
    <EntreeLayout panel={labels.signup.panel}>
      <VerifyLink token={null} />
      <LegalLinks />
    </EntreeLayout>
  );
}
