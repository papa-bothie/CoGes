import type { Metadata } from "next";
import { Suspense } from "react";

import { BrandLogo } from "@/components/brand/brand";
import { labels } from "@/lib/labels";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: labels.login.pageTitle };

const t = labels.login;

/**
 * Connexion, maquette v2 (écran 25) : à gauche le panneau vert (logo, « Votre boutique,
 * simplement. », les quatre rubriques), à droite le formulaire. Sur téléphone, le panneau
 * se réduit à son logo et sa phrase, au-dessus du formulaire.
 */
export default function LoginPage() {
  return (
    <main className="flex min-h-dvh flex-col bg-background md:flex-row">
      <section className="flex flex-col justify-between gap-8 bg-ventes-teinte px-6 py-8 text-marque md:min-h-dvh md:flex-1 md:px-12 md:py-14">
        <BrandLogo className="h-auto w-[220px] md:w-[318px]" />
        <div className="max-w-[420px] space-y-3">
          <p className="text-[34px] leading-[1.15] font-extrabold md:text-[44px]">{t.tagline}</p>
          <p className="text-lg text-marque/85 md:text-xl">{t.pitch}</p>
        </div>
        <ul className="hidden flex-wrap gap-2.5 md:flex" aria-hidden>
          {t.pills.map((pill) => (
            <li key={pill} className="rounded-full bg-card px-4 py-2.5 font-bold">
              {pill}
            </li>
          ))}
        </ul>
      </section>
      <section className="flex flex-1 items-center justify-center px-4 py-10 md:px-12">
        <div className="w-full max-w-[440px] space-y-6">
          <h1 className="text-[32px] leading-tight font-extrabold">{t.title}</h1>
          <Suspense>
            <LoginForm />
          </Suspense>
        </div>
      </section>
    </main>
  );
}
