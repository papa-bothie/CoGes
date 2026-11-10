import type { Metadata } from "next";
import Image from "next/image";

import { BrandMark, BrandWordmark } from "@/components/brand/brand";
import { LegalLinks } from "@/components/legal/legal-links";
import { HeroTitle } from "@/components/vitrine/hero-title";
import { ICONS, RUBRIQUE } from "@/components/vitrine/icons";
import { ButtonLink, WhatsAppLink } from "@/components/vitrine/links";
import { MiniCaisse } from "@/components/vitrine/mini-caisse";
import { motion, revele } from "@/components/vitrine/motion";
import { Revele } from "@/components/vitrine/revele";
import { VitrineHeader } from "@/components/vitrine/vitrine-header";
import { vitrine, whatsappLink } from "@/content/vitrine";
import { texte } from "@/content/vitrine-texte";
import { cn } from "@/lib/utils";

/**
 * Page d'accueil publique (prompt 37, ADR 0115), rendue au build. `proxy.ts` ne la montre
 * qu'à un visiteur nouveau : une session mène à l'Accueil, `coges_known` à la connexion.
 * Aucune requête à l'API, aucun formulaire, aucun script tiers.
 */
export const dynamic = "force-static";

const SHARE_IMAGE = "/vitrine/partage.png";

export const metadata: Metadata = {
  title: { absolute: texte.meta.title },
  description: texte.meta.description,
  alternates: { canonical: "/" },
  // La seule page indexable du site (la mise en page racine dit `noindex` pour le reste).
  robots: { index: true, follow: true },
  openGraph: {
    type: "website",
    locale: "fr_FR",
    url: "/",
    siteName: "CoGes",
    title: texte.meta.title,
    description: texte.meta.description,
    images: [{ url: SHARE_IMAGE, width: 1200, height: 630, alt: texte.meta.shareAlt }],
  },
  twitter: {
    card: "summary_large_image",
    title: texte.meta.title,
    description: texte.meta.description,
    images: [{ url: SHARE_IMAGE, alt: texte.meta.shareAlt }],
  },
};

/** Données structurées minimales : rien qui ne soit vrai et affiché (aucun prix, aucune note). */
function structuredData(): string {
  const data = [
    {
      "@context": "https://schema.org",
      "@type": "Organization",
      name: "CoGes",
      url: vitrine.siteUrl,
      logo: `${vitrine.siteUrl}/brand/coges-logo.png`,
      contactPoint: {
        "@type": "ContactPoint",
        contactType: "customer support",
        telephone: `+${vitrine.whatsappNumber}`,
        availableLanguage: "fr",
      },
    },
    {
      "@context": "https://schema.org",
      "@type": "SoftwareApplication",
      name: "CoGes",
      url: vitrine.siteUrl,
      applicationCategory: "BusinessApplication",
      operatingSystem: "Web",
      inLanguage: "fr",
      description: texte.meta.description,
    },
  ];
  // `<` échappé : le contenu ne peut jamais fermer la balise de script.
  return JSON.stringify(data).replace(/</g, "\\u003c");
}

function SectionTitle({
  id,
  title,
  lead,
  appear = true,
}: {
  id: string;
  title: string;
  lead?: string;
  /** Faux pour une section visible au premier affichage (jamais masquée, LCP). */
  appear?: boolean;
}) {
  const box = "mb-8 max-w-2xl space-y-3 md:mb-10";
  return (
    <div {...(appear ? revele(0, "monte", box) : { className: box })}>
      <h2 id={id} className="text-[28px] leading-tight font-extrabold md:text-[36px]">
        {title}
      </h2>
      {lead ? <p className="text-lg text-muted-foreground">{lead}</p> : null}
    </div>
  );
}

/**
 * Les illustrations (unDraw) gardent leurs couleurs de papier clair, en sombre aussi :
 * `.papier` reprend les jetons clairs (comme la facture A4, ADR 0112).
 */
function Illustration({
  src,
  width,
  height,
  className,
  appear,
}: {
  src: string;
  width: number;
  height: number;
  className?: string;
  /** Apparition au défilement (jamais pour l'illustration du hero). */
  appear?: "gauche" | "droite";
}) {
  const panel = cn("papier rounded-carte bg-voile p-6 md:p-8", className);
  return (
    <div {...(appear ? revele(0, appear, panel) : { className: panel })}>
      <Image
        src={src}
        alt=""
        width={width}
        height={height}
        unoptimized
        loading="lazy"
        className="h-auto w-full"
      />
    </div>
  );
}

export default function VitrinePage() {
  const t = texte;
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: structuredData() }} />
      <a
        href="#contenu"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-mini focus:bg-card focus:px-4 focus:py-3 focus:font-bold focus:shadow-lg"
      >
        Aller au contenu
      </a>
      <div id="haut" className="min-h-dvh bg-background text-foreground">
        <VitrineHeader />

        <main id="contenu">
          {/* Hero */}
          <section
            aria-labelledby="titre"
            className="mx-auto grid max-w-page items-center gap-10 overflow-x-clip px-4 pt-10 pb-16 md:grid-cols-[1.1fr_0.9fr] md:px-marge-page md:pt-16 md:pb-24"
          >
            {/* Rien n'entre en fondu dans le hero : tout est là au premier affichage (LCP). */}
            <div className={cn(motion.pause, "space-y-6")}>
              <HeroTitle className="text-[34px] leading-[1.1] font-extrabold tracking-[-0.01em] text-marque md:text-[44px] lg:text-[52px] dark:text-foreground" />
              <p className="max-w-xl text-lg text-encre-2 md:text-xl dark:text-muted-foreground">
                {t.hero.lead}
              </p>
              <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
                <WhatsAppLink className={cn(motion.eclat, "min-h-bouton text-libelle")}>
                  {t.hero.whatsapp}
                </WhatsAppLink>
                <a
                  href="#comment"
                  className="inline-flex min-h-bouton items-center justify-center rounded-bouton border-2 border-input bg-card px-5 text-libelle font-bold text-foreground outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/60"
                >
                  {t.hero.howItWorks}
                </a>
              </div>
              <p className="font-semibold text-success-ink">{t.hero.trial}</p>
            </div>
            {/* A9 : la mini-caisse remplace l'illustration de la boutique (ADR 0116). */}
            <div className={cn(motion.halo, "mx-auto w-full max-w-[420px]")}>
              <MiniCaisse />
            </div>
          </section>

          {/* Problème / solution */}
          <section aria-labelledby="questions-du-jour" className="bg-card py-16 md:py-20">
            <div className="mx-auto max-w-page px-4 md:px-marge-page">
              {/* Visible dès le premier affichage à partir de 768 px : aucune apparition ici. */}
              <SectionTitle id="questions-du-jour" title={t.problems.title} appear={false} />
              <ul className="grid gap-4 sm:grid-cols-2">
                {t.problems.items.map((item) => {
                  const Icon = ICONS[item.icon];
                  const color = RUBRIQUE[item.rubrique];
                  return (
                    <li
                      key={item.question}
                      className={cn(motion.carte, "rounded-carte p-carte", color.tint)}
                    >
                      <span
                        className={cn(
                          motion.icone,
                          "mb-4 inline-flex size-12 items-center justify-center rounded-touche text-primary-foreground",
                          color.solid,
                        )}
                      >
                        <Icon aria-hidden className="size-6" />
                      </span>
                      <h3 className={cn("mb-2 text-xl font-extrabold", color.ink)}>
                        {item.question}
                      </h3>
                      <p className="text-foreground">{item.answer}</p>
                    </li>
                  );
                })}
              </ul>
            </div>
          </section>

          {/* Fonctionnalités */}
          <section
            id="fonctionnalites"
            aria-labelledby="titre-fonctionnalites"
            className="scroll-mt-20 py-16 md:py-24"
          >
            <div className="mx-auto max-w-page px-4 md:px-marge-page">
              <SectionTitle
                id="titre-fonctionnalites"
                title={t.features.title}
                lead={t.features.lead}
              />
              <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {t.features.items.map((item, index) => {
                  const Icon = ICONS[item.icon];
                  const color = RUBRIQUE[item.rubrique];
                  return (
                    <li
                      key={item.title}
                      {...revele(
                        index % 3,
                        "monte",
                        cn(motion.carte, "rounded-carte border border-border bg-card p-carte"),
                      )}
                    >
                      <span
                        className={cn(
                          motion.icone,
                          "mb-4 inline-flex size-12 items-center justify-center rounded-touche",
                          color.tint,
                          color.ink,
                        )}
                      >
                        <Icon aria-hidden className="size-6" />
                      </span>
                      <h3 className="mb-2 text-xl font-extrabold">{item.title}</h3>
                      <p className="text-muted-foreground">{item.body}</p>
                    </li>
                  );
                })}
              </ul>
            </div>
          </section>

          {/* Aperçu */}
          <section
            id="comment"
            aria-labelledby="titre-apercu"
            className="scroll-mt-20 bg-ventes-teinte py-16 md:py-24"
          >
            <div className="mx-auto max-w-page px-4 md:px-marge-page">
              <SectionTitle id="titre-apercu" title={t.preview.title} lead={t.preview.lead} />
              <div className="flex flex-col items-center gap-10 lg:flex-row lg:items-end lg:justify-center">
                <figure {...revele(0, "gauche", "w-full max-w-[720px] space-y-3")}>
                  <div className="overflow-hidden rounded-carte border-[6px] border-foreground bg-foreground shadow-xl">
                    <div aria-hidden className="flex h-5 items-center gap-1.5 px-2">
                      <span className="size-2 rounded-full bg-background/50" />
                      <span className="size-2 rounded-full bg-background/50" />
                      <span className="size-2 rounded-full bg-background/50" />
                    </div>
                    <Image
                      src="/vitrine/apercu-ordinateur.webp"
                      alt={t.preview.desktopAlt}
                      width={1280}
                      height={800}
                      unoptimized
                      loading="lazy"
                      className="h-auto w-full rounded-b-mini"
                    />
                  </div>
                  <figcaption className="text-center font-semibold text-ventes-encre">
                    {t.preview.desktopCaption}
                  </figcaption>
                </figure>
                <figure {...revele(1, "droite", "w-full max-w-[260px] space-y-3")}>
                  <div className="overflow-hidden rounded-[36px] border-[8px] border-foreground bg-foreground shadow-xl">
                    <Image
                      src="/vitrine/apercu-telephone.webp"
                      alt={t.preview.phoneAlt}
                      width={390}
                      height={844}
                      unoptimized
                      loading="lazy"
                      className="h-auto w-full rounded-[28px]"
                    />
                  </div>
                  <figcaption className="text-center font-semibold text-ventes-encre">
                    {t.preview.phoneCaption}
                  </figcaption>
                </figure>
              </div>
            </div>
          </section>

          {/* Avantages */}
          <section aria-labelledby="titre-avantages" className="py-16 md:py-24">
            <div className="mx-auto grid max-w-page items-center gap-10 px-4 md:grid-cols-[0.9fr_1.1fr] md:px-marge-page">
              <Illustration
                src="/vitrine/illustration-chiffres.svg"
                width={960}
                height={637}
                appear="gauche"
                className="order-last md:order-first"
              />
              <div>
                <SectionTitle id="titre-avantages" title={t.benefits.title} />
                <ul className="space-y-6">
                  {t.benefits.items.map((item, index) => {
                    const Icon = ICONS[item.icon];
                    return (
                      <li key={item.title} {...revele(index, "monte", "flex gap-4")}>
                        <span className="inline-flex size-12 shrink-0 items-center justify-center rounded-touche bg-ventes-teinte text-ventes-encre">
                          <Icon aria-hidden className="size-6" />
                        </span>
                        <div>
                          <h3 className="mb-1 text-xl font-extrabold">{item.title}</h3>
                          <p className="text-muted-foreground">{item.body}</p>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </div>
            </div>
          </section>

          {/* Questions fréquentes : <details> natif, sans JavaScript. */}
          <section
            id="questions"
            aria-labelledby="titre-questions"
            className="scroll-mt-20 bg-card py-16 md:py-24"
          >
            <div className="mx-auto grid max-w-page gap-10 px-4 md:px-marge-page lg:grid-cols-[1fr_1.4fr]">
              <div>
                <SectionTitle id="titre-questions" title={t.faq.title} />
                <Illustration
                  src="/vitrine/illustration-stock.svg"
                  width={800}
                  height={406}
                  className="hidden lg:block"
                />
              </div>
              <div
                {...revele(
                  0,
                  "monte",
                  cn(motion.faq, "divide-y divide-border rounded-carte border border-border"),
                )}
              >
                {t.faq.items.map((item) => (
                  <details key={item.question} className={cn(motion.question, "group px-5")}>
                    <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-4 py-3 text-libelle font-bold outline-none focus-visible:ring-3 focus-visible:ring-ring/60 [&::-webkit-details-marker]:hidden">
                      {item.question}
                      <span
                        aria-hidden
                        className="text-2xl leading-none text-muted-foreground transition-transform group-open:rotate-45 motion-reduce:transition-none"
                      >
                        +
                      </span>
                    </summary>
                    <p className="pb-5 text-muted-foreground">{item.answer}</p>
                  </details>
                ))}
              </div>
            </div>
          </section>

          {/* Dernier appel */}
          <section aria-labelledby="titre-contact" className="py-16 md:py-20">
            <div className="mx-auto max-w-page px-4 md:px-marge-page">
              <div
                {...revele(
                  0,
                  "monte",
                  "flex flex-col items-start gap-6 rounded-carte bg-marque p-8 text-primary-foreground md:flex-row md:items-center md:justify-between md:p-12 dark:bg-ventes-teinte dark:text-foreground",
                )}
              >
                <div className="space-y-2">
                  <h2 id="titre-contact" className="text-[28px] leading-tight font-extrabold">
                    Une question ? Écrivez-nous.
                  </h2>
                  <p className="text-lg opacity-90">{vitrine.supportHours}</p>
                </div>
                <WhatsAppLink
                  variant="borde"
                  className="min-h-bouton border-transparent text-libelle"
                >
                  {t.hero.whatsapp}
                </WhatsAppLink>
              </div>
            </div>
          </section>
        </main>

        <footer className="border-t border-border bg-card">
          <div className="mx-auto flex max-w-page flex-col gap-6 px-4 py-10 md:flex-row md:items-start md:justify-between md:px-marge-page">
            <div className="space-y-3">
              <div className="flex items-center gap-2.5">
                <BrandMark />
                <BrandWordmark />
              </div>
              <p className="text-muted-foreground">{t.footer.tagline}</p>
            </div>
            <div className="space-y-2">
              <a
                href={whatsappLink()}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex min-h-cible items-center font-bold text-success-ink underline underline-offset-4"
              >
                {t.footer.contact}
              </a>
              <p className="text-muted-foreground">{t.footer.hours}</p>
              <ButtonLink href="/login" variant="borde">
                {t.footer.login}
              </ButtonLink>
            </div>
          </div>
          <div className="mx-auto flex max-w-page flex-col gap-1 px-4 pb-8 md:flex-row md:items-center md:justify-between md:px-marge-page">
            <LegalLinks />
            <p className="text-mini text-muted-foreground">{t.footer.copyright}</p>
          </div>
        </footer>
      </div>
      <Revele />
    </>
  );
}
