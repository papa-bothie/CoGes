import { BrandMark, BrandWordmark } from "@/components/brand/brand";
import { texte } from "@/content/vitrine-texte";

import { ButtonLink, WhatsAppLink } from "./links";
import { MobileMenu } from "./mobile-menu";

const t = texte.nav;

/**
 * En-tête de la vitrine : « Se connecter » visible dès le premier écran et à toute largeur
 * (un commerçant qui a vidé ses cookies ou changé d'appareil arrive ici, ADR 0115).
 */
export function VitrineHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/85">
      <div className="relative mx-auto flex h-18 max-w-page items-center justify-between gap-3 px-4 md:px-marge-page">
        <a
          href="#haut"
          className="flex items-center gap-2.5 rounded-mini outline-none focus-visible:ring-3 focus-visible:ring-ring/60"
        >
          <BrandMark />
          <BrandWordmark className="max-[389px]:hidden" />
          <span className="sr-only">{t.home}</span>
        </a>
        <nav aria-label="Principal" className="hidden items-center gap-1 md:flex">
          <a
            href="#fonctionnalites"
            className="flex min-h-cible items-center rounded-mini px-3 font-semibold hover:bg-voile"
          >
            {t.features}
          </a>
          <a
            href="#questions"
            className="flex min-h-cible items-center rounded-mini px-3 font-semibold hover:bg-voile"
          >
            {t.questions}
          </a>
        </nav>
        <div className="flex items-center gap-2">
          <WhatsAppLink variant="borde" className="hidden md:inline-flex">
            {t.whatsapp}
          </WhatsAppLink>
          <ButtonLink href="/login" className="px-4">
            {t.login}
          </ButtonLink>
          <MobileMenu />
        </div>
      </div>
    </header>
  );
}
