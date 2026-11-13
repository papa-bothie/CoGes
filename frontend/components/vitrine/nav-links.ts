import { texte } from "@/content/vitrine-texte";

/**
 * Liens de la navigation de la vitrine, partagés par l'en-tête et le menu du téléphone
 * (prompt 39, bloc N, ADR 0123). Chaque ancre est l'`id` d'une section de la page
 * (`nav-links.test.ts`), focalisable (`tabIndex={-1}`) et décalée sous l'en-tête collant.
 */
export const NAV_LINKS = [
  { anchor: "fonctionnalites", label: texte.nav.features },
  { anchor: "comment", label: texte.nav.howItWorks },
  { anchor: "questions", label: texte.nav.questions },
] as const;
