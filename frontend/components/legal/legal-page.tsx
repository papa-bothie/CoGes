import Link from "next/link";

import { BrandMark, BrandWordmark } from "@/components/brand/brand";
import { ButtonLink } from "@/components/vitrine/links";
import { LegalMarkdown } from "@/components/legal/legal-markdown";
import { LegalLinks } from "@/components/legal/legal-links";
import { texte } from "@/content/vitrine-texte";
import { legalDocument, type LegalSlug } from "@/lib/legal/documents";
import { displayVersion } from "@/lib/legal/parse";
import { labels } from "@/lib/labels";

const t = labels.legal;

/**
 * Page d'un texte légal (prompt 36, ADR 0117), rendue au build depuis `content/legal/` :
 * aucune requête à l'API, aucune connexion demandée. En-tête et pied sobres de la vitrine,
 * colonne de lecture étroite, date de version en tête (lue dans le fichier).
 */
export function LegalPage({ slug }: { slug: LegalSlug }) {
  const document = legalDocument(slug);
  return (
    <div className="min-h-dvh bg-background text-foreground">
      <a
        href="#contenu"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-mini focus:bg-card focus:px-4 focus:py-3 focus:font-bold focus:shadow-lg"
      >
        {labels.app.skipToContent}
      </a>
      <header className="border-b border-border bg-background">
        <div className="mx-auto flex h-18 max-w-page items-center justify-between gap-3 px-4 md:px-marge-page">
          <Link
            href="/"
            className="flex min-h-cible items-center gap-2.5 rounded-mini outline-none focus-visible:ring-3 focus-visible:ring-ring/60"
          >
            <BrandMark />
            <BrandWordmark className="max-[389px]:hidden" />
            <span className="sr-only">{t.backHome}</span>
          </Link>
          <ButtonLink href="/login" className="px-4">
            {t.login}
          </ButtonLink>
        </div>
      </header>

      <main
        id="contenu"
        tabIndex={-1}
        className="px-4 pt-8 pb-16 outline-none md:px-marge-page md:pt-12"
      >
        <article className="mx-auto max-w-[72ch] space-y-4 text-base leading-relaxed text-encre-2 md:text-lg">
          <header className="space-y-3 pb-2">
            <p className="inline-flex rounded-full bg-ventes-teinte px-3 py-1 text-mini font-bold text-marque">
              <time dateTime={document.version}>{t.version(displayVersion(document.version))}</time>
            </p>
            <h1 className="text-[30px] leading-tight font-extrabold text-foreground md:text-[40px]">
              {document.title}
            </h1>
          </header>
          <LegalMarkdown tokens={document.tokens} />
        </article>
      </main>

      <footer className="border-t border-border bg-card">
        <div className="mx-auto flex max-w-page flex-col gap-2 px-4 py-8 md:flex-row md:items-center md:justify-between md:px-marge-page">
          <LegalLinks />
          <p className="text-mini text-muted-foreground">{texte.footer.copyright}</p>
        </div>
      </footer>
    </div>
  );
}
