# 0132 — Offres Pro et Business, droits par offre, droits acquis, « Mon abonnement »

- **Date** : 2026-11-26
- **Phase** : lot B (`docs/prompts/41-offres-pro-business-et-droits.md`)
- **Statut** : acceptée — **amende l'ADR 0091** (catalogue, essai, `features`), et l'ADR 0125
  (licence : Premium accepté, `is_license`)
- **Décideur** : propriétaire (décisions des 23 et 26 novembre 2026, écrites dans le prompt) et
  utilisateur (AskUserQuestion du 26 novembre 2026)

## Contexte

L'ADR 0091 avait posé trois offres mensuelles (Starter, Business, Premium), un essai Premium et
une colonne `plans.features` « indicative » : rien n'était réservé à une offre. Le propriétaire
arrête maintenant deux offres en vente, Pro (4 900 FCFA, 3 comptes) et Business (9 900 FCFA,
7 comptes), Premium sur devis, un paiement annuel à -10 %, un essai sur Pro, et réserve l'import
Excel/CSV à Business. Les boutiques existantes passent sur Pro sans rien perdre.

Contraintes héritées : `coges_app` ne lit aucune table de la plateforme (ADR 0091), les codes
d'offre servent à la licence sur site (ADR 0125), et la migration doit être un ajout que le code
en production ignore (ADR 0083).

## Décisions de l'utilisateur (AskUserQuestion)

- **Support de Business : « Support prioritaire »**, avec les horaires actuels du support
  (`vitrine.supportHours`), pas de 24/7.
- **`GET /api/v1/subscription` : gérant seul, `company:update`.** Le comptable a `company:read`
  et ne voit pas l'échéance ni le paiement ; tout rôle lit le nom et les droits de l'offre dans
  `/auth/me`, pour verrouiller les écrans.
- **Aucun numéro Wave ou Orange Money affiché** : « Comment payer » propose WhatsApp prérempli,
  l'équipe donne le numéro dans la conversation (en attendant le paiement en ligne, lot D).
- **Licence reconnue par une colonne `subscriptions.is_license`**, posée par `activate-license`,
  plutôt que déduite (« actif sans fin de période ») : un abonnement mis actif à la main en ligne
  ne passerait pas pour une licence.

## Décisions prises dans le plan, sans objection

- Premium (prix `NULL`, sur devis) se paie **d'un montant libre** (positif), pour un mois ou un
  an ; Pro et Business exigent exactement le prix du mois ou de l'année.
- « Changer d'offre » (administrateur) et `activate-license` acceptent Premium bien qu'il ne soit
  plus en vente libre (`QUOTED_PLANS`). Tout autre palier non vendable reste refusé.

## Décision

### Catalogue (révision 0043)

| Code (inchangé) | Nom | Mois | An (écrit en base) | Comptes | Vendable |
|---|---|---|---|---|---|
| `starter` | Pro | 4 900 | 52 920 | 3 | oui |
| `business` | Business | 9 900 | 106 920 | 7 | oui |
| `premium` | Premium | sur devis | — | 10 | non |

`plans.annual_price_fcfa` (`numeric(14,2)`, `NULL` = pas à l'année, `CHECK` : jamais sans prix
mensuel) est **écrit**, jamais recalculé ; un test vérifie 12 × prix × 0,9.

### Catalogue fermé des droits

`plans.features` devient la source des droits. Codes, dans `app/core/plan_features.py` (testé,
copié tel quel dans la révision) :

- **communs** (Pro, Business, Premium) : `sales`, `purchases`, `inventory`, `dashboard`,
  `reports_exports`, `product_photos`, `documents`, `stock_alerts` ;
- **Business et Premium** : `imports`, `physical_inventory` (lot E), `invoice_branding` (lot E),
  `stock_locations` (lot F), `priority_support`.

Les trois codes des lots E et F existent mais ne protègent encore rien. Seul `imports` est
contrôlé dans ce lot. Seuls les droits réservés à Business s'accordent en droit acquis
(`GRANTABLE`).

### Essai et boutiques existantes

- `companies_start_trial()` démarre l'essai de 30 jours sur `starter`.
- **Toutes** les entreprises présentes à la migration (essai, payées, suspendues, licences)
  passent sur `starter`, sans changer `status`, `trial_ends_at`, `current_period_end`,
  `started_at` ni `updated_at`. **Droits acquis** : `subscriptions.extra_features` reçoit
  `["imports"]` ; `subscriptions.max_users_override` reçoit leur nombre de comptes actifs quand il
  dépasse 3. `is_license` est vrai pour un abonnement actif sans fin de période dont le journal
  de la plateforme porte la raison « licence sur site ».
- `users_plan_limit()` : plafond = `COALESCE(max_users_override, plans.max_users)`. Même verrou
  `FOR UPDATE` sur l'abonnement, même `CG007`.

### Lire les droits : `current_plan()`

Fonction `SECURITY DEFINER` de `coges_billing` (NOLOGIN, sans BYPASSRLS), `search_path` figé,
`EXECUTE` à `coges_app` seul. Elle rend, pour l'entreprise de `app.company_id` et elle seule
(filtre **et** RLS de `subscriptions` et `users`) : code et nom de l'offre, statut, fin d'essai,
fin de période, `is_license`, plafond effectif, comptes actifs, droits effectifs (offre + droits
acquis, sans doublon) et droits acquis. Sans contexte, aucune ligne. `coges_app` n'a toujours
aucun droit sur `plans`, `subscriptions`, `subscription_payments` (T36).

### Côté API

- `require_feature(code)` (`app/core/deps.py`), à côté de `require_permission` : lit
  `current_plan()` **une fois par requête** (`request.state`) ; droit absent ⇒ **403
  `plan_feature_required`**, `details = {feature, required_plan: "business"}`, message « Cette
  fonction est disponible avec l'offre Business. ».
- Appliqué à `POST /imports/{kind}` (envoi et simulation) et `GET /imports/{kind}/template`.
  Les exports restent ouverts à toutes les offres.
- **Registre** `tests/architecture/test_plan_feature_routes.py` : toute route protégée par un
  droit d'offre y est déclarée, et toute route sous `/api/v1/imports` doit exiger `imports`.
- `GET /auth/me` gagne `plan {code, name, status, is_license, features}`.
- `GET /api/v1/subscription` (`company:update`) : offre, statut, échéances, `is_license`, plafond
  effectif, comptes actifs, droits effectifs et acquis. **Sans prix** : les prix de l'écran
  viennent de la source partagée du front.

### Plateforme

- `POST /platform/companies/{id}/payments` : `period_months` (1 ou 12, défaut 1, colonne
  `subscription_payments.period_months`). Montant égal à `price_fcfa` (1 mois) ou
  `annual_price_fcfa` (12 mois), sinon **422 `payment_amount_mismatch`** avec
  `expected_amount_fcfa` ; 12 mois sur une offre sans prix annuel : 422
  `annual_payment_unavailable`. La fin avance de 1 ou 12 mois depuis la plus lointaine
  d'aujourd'hui et de la fin en cours (dernier jour du mois si le jour n'existe pas).
  Idempotence et audit inchangés (l'audit note `period_months`).
- `PUT /platform/companies/{id}/subscription/acquired-rights` (administrateur) : remplace
  `extra_features` et `max_users_override`, raison obligatoire, audit critique (avant/après),
  rien d'écrit si rien ne change ; un plafond (acquis, ou celui de l'offre s'il est retiré) plus
  bas que les comptes actifs ⇒ 409 `plan_downgrade_too_many_users`. Code inconnu ou non
  accordable ⇒ 422 `unknown_feature`.
- `SubscriptionDetail` gagne `is_license`, `extra_features`, `max_users_override`, `max_users`
  (effectif) ; `PlanRead` gagne `annual_price_fcfa`. La descente d'offre compte le plafond acquis.
- `activate-license` pose `is_license = true` ; son audit compare aussi `license`.

### Écrans

- **Front commerçant** : `content/offres.json` est la **seule** source des montants (vitrine et
  « Mon abonnement ») ; `tests/integration/test_plan_features.py` la compare à la table `plans`.
  `lib/offres.ts` porte les libellés des droits en mots simples (les fonctions des lots E et F
  sont dites « bientôt »).
- « Mon abonnement » (`/settings/subscription`, registre `lib/access.ts`) : « CoGes Pro »,
  « Essai gratuit jusqu'au 25 décembre 2026 », « Payé jusqu'au … », « Suspendu », « Licence sur
  site, offre Pro » (sans paiement ni échéance), « 2 comptes sur 3 », contenu de l'offre, ce
  qu'ajoute Business, droits acquis (« Import inclus pour votre boutique »), « Comment payer » :
  deux montants et WhatsApp prérempli (« Je veux payer CoGes Pro pour 1 mois. »).
- Import verrouillé : dans « Fichiers Excel », la carte d'import est remplacée par
  `LockedFeatureCard` (badge « Business », « Disponible avec Business », « Passer à Business »
  par WhatsApp). **Écart au prompt** : le badge est sur la carte, pas sur l'entrée de menu
  « Fichiers Excel », qui ouvre aussi les exports (ouverts à tous) et serait trompeuse.
  `plan_feature_required` est montré par son message, jamais en 403 brut.
- Vitrine : section « Nos offres » (deux cartes, Premium sur devis, « 30 jours d'essai gratuit
  sur Pro »), bascule « Par mois / Par an (-10 %) » en deux boutons radio et `:has()`, **sans
  JavaScript**. Gardes de `vitrine-texte.test.ts` remplacées : aucun prix écrit dans les textes,
  montants de la seule source (`components/vitrine/offres.test.tsx`), « 10 % » dans la bascule
  seulement. La FAQ « Combien coûte CoGes ? » renvoie à la section. La garde « aucun formulaire » de
  `e2e/vitrine.spec.ts` admet ces deux seuls boutons radio, hors de tout `<form>` (ils ne
  montrent que l'autre prix, rien n'est envoyé).
- Administration : durée « 1 mois / 1 an (-10 %) » avec montant prérempli, offres vendables plus
  Premium sur devis, ligne « Droits acquis » et formulaire (cases, plafond, raison), durée dans
  la liste des paiements et dans le journal.

## Conséquences

- La migration exige `coges_billing` (déjà là depuis 0028) ; rien à lancer sur Neon avant.
- Le retour arrière (`downgrade`) retire colonnes et fonction et remet les noms, prix et
  fonctions de 0091 ; il ne remet **pas** les boutiques sur leur offre d'avant (elles restent sur
  `starter`, sans plafond acquis).
- Les entreprises partagées par la suite de tests (palier `sur_devis`) reçoivent tout le
  catalogue de droits ; le plafond et les droits ont leurs tests sur des boutiques neuves. Un
  test qui redescend sous 0043 puis remonte (0043 recopie **toutes** les entreprises) prend la
  fixture `subscriptions_kept`. En e2e, `demo` et `maquette` passent sur Business (elles
  montrent tout le produit, dont l'écran 24e de la maquette) et `offres-e2e` reste en essai Pro.
- Localement, `make seed-demo` et `make seed-maquette` créent leur boutique en essai Pro
  (import verrouillé) : c'est le comportement réel d'une boutique neuve.
- Les CGU (`frontend/content/legal/conditions.md`) citent encore l'essai Premium et l'ancien
  tableau : à corriger par le propriétaire, puis nouvelle version des textes.
- Hors lot : relances et suspension (C), paiement en ligne (D), inventaire, facture
  personnalisée (E), dépôt-réserve (F).

## Amendement — prompt 42 (27 novembre 2026) : « Tarifs » et carte « Essai gratuit »

Demande du propriétaire (`docs/prompts/42-vitrine-tarifs-et-essai.md`), sans migration ni route.

- **Navigation** : « Comment ça marche » (`nav.howItWorks`, retiré) devient « Tarifs »
  (`nav.pricing`), vers `#offres`, dans l'en-tête et le menu du téléphone (`NAV_LINKS`). La
  section `#comment` reste à sa place. Comme les autres ancres (ADR 0123), la section
  `#offres` (`tabIndex={-1}`, nommée par son titre) reçoit le focus ; `scroll-mt-20` (80 px) la
  pose sous l'en-tête de 72 px.
- **Carte « Essai gratuit »**, la première des trois (Essai, Pro, Business ; Premium reste en
  dessous) : « 0 F » tiré de `offres.json` (`trialPrice`, nouvelle clé, vérifiée par le test
  backend), « pendant N jours » (`trialDays`), « Toutes les fonctions de CoGes <offre de
  `trialPlan`> », « Aucun paiement pour commencer ». Sans `data-periode` : la bascule annuelle
  ne la touche pas. Le bouton « Démarrer l'essai gratuit » mène à `/inscription` quand
  l'inscription est ouverte (même condition que « Créer ma boutique », `signupConfig()` lu par
  le serveur), sinon à WhatsApp avec « Je veux essayer CoGes gratuitement. » (`trialLink()`).
- **Mise en page** : trois colonnes dès 1024 px (`lg`), empilées en dessous. La carte d'essai
  garde une bordure fine et porte l'étiquette « Pour commencer » (`ventes-teinte` /
  `ventes-encre`). Business reste la seule bordée de vert.
- **Gardes** : « 0 F » n'apparaît que dans la carte d'essai (`offres.test.tsx`, avec un
  témoin), aucun montant écrit dans `texte.offers.trialCard` (`vitrine-texte.test.ts`).
