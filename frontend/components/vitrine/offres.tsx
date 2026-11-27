import { Check } from "lucide-react";

import { ButtonLink, WhatsAppLink } from "@/components/vitrine/links";
import { revele } from "@/components/vitrine/motion";
import { texte } from "@/content/vitrine-texte";
import { formatAmount } from "@/lib/format/money";
import {
  BUSINESS,
  BUSINESS_EXTRAS,
  FEATURE_LABELS,
  type Offre,
  PRO,
  TRIAL_PRICE,
  amount,
  trialLink,
} from "@/lib/offres";
import { cn } from "@/lib/utils";

import styles from "./vitrine.module.css";

const t = texte.offers;

function Price({ value, period, periode }: { value: number; period: string; periode: string }) {
  return (
    <p data-periode={periode} className="text-lg">
      <span className="text-[32px] leading-tight font-extrabold numeric">
        {formatAmount(amount(value))}
      </span>{" "}
      <span className="text-muted-foreground">{period}</span>
    </p>
  );
}

/**
 * Première carte (prompt 42) : l'essai, « 0 F » de la source partagée, pareil par mois et par
 * an (aucun `data-periode` : la bascule ne la touche pas). Bordure fine et étiquette « Pour
 * commencer » : elle se distingue sans prendre le dessus sur Business, seul bordé de vert.
 * Bouton : l'inscription quand elle est ouverte (même condition que « Créer ma boutique »),
 * sinon WhatsApp avec un message prérempli.
 */
function TrialCard({ signupEnabled }: { signupEnabled: boolean }) {
  const card = t.trialCard;
  const button = "mt-auto w-full";
  return (
    <li
      {...revele(0, "monte", "flex flex-col gap-4 rounded-carte border border-border bg-card p-6")}
    >
      <p className="self-start rounded-full bg-ventes-teinte px-3 py-1 text-sm font-bold text-ventes-encre">
        {card.badge}
      </p>
      <h3 className="text-2xl font-extrabold">{card.name}</h3>
      <p className="text-lg">
        <span className="text-[32px] leading-tight font-extrabold numeric">
          {formatAmount(amount(TRIAL_PRICE))}
        </span>{" "}
        <span className="text-muted-foreground">{card.period}</span>
      </p>
      <ul className="space-y-2">
        {[card.includes, card.noPayment].map((line) => (
          <li key={line} className="flex items-start gap-2.5">
            <Check aria-hidden className="mt-0.5 size-5 shrink-0 text-ventes-encre" />
            <span>{line}</span>
          </li>
        ))}
      </ul>
      {signupEnabled ? (
        <ButtonLink href="/inscription" className={button}>
          {card.cta}
        </ButtonLink>
      ) : (
        <WhatsAppLink href={trialLink()} className={button}>
          {card.cta}
        </WhatsAppLink>
      )}
    </li>
  );
}

function OfferCard({ offer, index }: { offer: Offre; index: number }) {
  const isPro = offer.code === PRO.code;
  const listed = isPro ? PRO.features : BUSINESS_EXTRAS;
  return (
    <li
      {...revele(
        index,
        "monte",
        cn(
          "flex flex-col gap-4 rounded-carte border bg-card p-6",
          isPro ? "border-border" : "border-2 border-primary",
        ),
      )}
    >
      <h3 className="text-2xl font-extrabold">CoGes {offer.name}</h3>
      <div>
        <Price value={offer.monthly!} period={t.perMonth} periode="mois" />
        <Price value={offer.annual!} period={t.perYear} periode="an" />
      </div>
      <p className="font-bold">{t.users(offer.maxUsers)}</p>
      {!isPro && <p className="text-muted-foreground">{t.everythingIn(PRO.name)}</p>}
      <ul className="space-y-2">
        {listed.map((code) => (
          <li key={code} className="flex items-start gap-2.5">
            <Check aria-hidden className="mt-0.5 size-5 shrink-0 text-ventes-encre" />
            <span>{FEATURE_LABELS[code]}</span>
          </li>
        ))}
      </ul>
      {isPro && <p className="mt-auto font-bold text-ventes-encre">{t.trial}</p>}
    </li>
  );
}

/**
 * « Nos offres » de la vitrine (prompt 41, B5, ADR 0132). Les montants viennent de
 * `content/offres.json` (une seule source, testée contre la table `plans`). La bascule
 * « Par mois / Par an » est faite de deux boutons radio et de `:has()` : aucun script.
 */
export function NosOffres({ signupEnabled }: { signupEnabled: boolean }) {
  return (
    <section
      id="offres"
      tabIndex={-1}
      aria-labelledby="titre-offres"
      className={cn(styles.offres, "scroll-mt-20 py-16 outline-none md:py-24")}
    >
      <div className="mx-auto max-w-page px-4 md:px-marge-page">
        <div {...revele(0, "monte", "mb-8 max-w-2xl space-y-3 md:mb-10")}>
          <h2 id="titre-offres" className="text-[28px] leading-tight font-extrabold md:text-[36px]">
            {t.title}
          </h2>
          <p className="text-lg text-muted-foreground">{t.lead}</p>
        </div>
        <fieldset className="mb-8 inline-flex rounded-full border border-border bg-card p-1">
          <legend className="sr-only">{t.period}</legend>
          {(
            [
              ["mois", t.monthly],
              ["an", t.annual],
            ] as const
          ).map(([value, label]) => (
            <label
              key={value}
              className="inline-flex min-h-cible cursor-pointer items-center rounded-full px-5 font-bold has-checked:bg-primary has-checked:text-primary-foreground has-focus-visible:ring-3 has-focus-visible:ring-ring/60"
            >
              <input
                type="radio"
                name="periode"
                value={value}
                defaultChecked={value === "mois"}
                className="sr-only"
              />
              {label}
            </label>
          ))}
        </fieldset>
        <ul className="grid gap-5 lg:grid-cols-3">
          <TrialCard signupEnabled={signupEnabled} />
          {[PRO, BUSINESS].map((offer, index) => (
            <OfferCard key={offer.code} offer={offer} index={index + 1} />
          ))}
        </ul>
        <p className="mt-5 font-bold text-muted-foreground">{t.durations}</p>
        <div className="mt-6 flex flex-col items-start gap-3 rounded-carte bg-card p-5 md:flex-row md:items-center md:justify-between">
          <p className="font-bold">{t.premium}</p>
          <WhatsAppLink variant="borde">{t.premiumLink}</WhatsAppLink>
        </div>
      </div>
    </section>
  );
}
