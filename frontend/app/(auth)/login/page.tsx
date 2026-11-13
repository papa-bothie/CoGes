import type { Metadata } from "next";
import { Suspense } from "react";

import { EntreeLayout } from "@/components/auth/entree-layout";
import { LegalLinks } from "@/components/legal/legal-links";
import { ButtonLink } from "@/components/vitrine/links";
import { signupConfig } from "@/lib/signup/config";
import { labels } from "@/lib/labels";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: labels.login.pageTitle };

/** « Créer ma boutique » paraît si l'inscription est ouverte : relu par le serveur au plus
 *  toutes les 5 minutes (ADR 0118). */
export const revalidate = 300;

const t = labels.login;

/**
 * Connexion, maquette v2 (écran 25) : panneau vert et formulaire, par la mise en page partagée
 * avec l'inscription (`EntreeLayout`, prompt 39).
 */
export default async function LoginPage() {
  const signup = await signupConfig();
  return (
    <EntreeLayout panel={t}>
      <h1 className="text-[32px] leading-tight font-extrabold">{t.title}</h1>
      <Suspense>
        <LoginForm />
      </Suspense>
      {signup.enabled && (
        <div className="flex flex-wrap items-center gap-3 border-t border-border pt-5">
          <p className="text-lg text-encre-2">{t.createShop}</p>
          <ButtonLink href="/inscription" variant="borde">
            {labels.signup.cta}
          </ButtonLink>
        </div>
      )}
      <LegalLinks className="pt-2" />
    </EntreeLayout>
  );
}
