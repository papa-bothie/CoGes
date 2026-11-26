# Prompt 41 — Lot B : offres Pro et Business, droits par offre, « Mon abonnement »

> Deuxième lot du plan `plan-offres-paiement-et-retouches.md`. Audit fait sur `main` au commit `cf9576e` (26 novembre 2026, lot A fusionné : PR #102, ADR 0130).
>
> **Décisions du propriétaire (23 et 26 novembre 2026), à ne pas rouvrir :**
> - Deux offres en vente : **Pro 4 900 FCFA/mois** (3 comptes) et **Business 9 900 FCFA/mois** (7 comptes). **Premium devient « sur devis »** (plus en vente libre).
> - Paiement d'un an : **10 % de réduction**, soit **52 920 FCFA/an** (Pro) et **106 920 FCFA/an** (Business).
> - **L'essai de 30 jours se fait sur Pro.**
> - **Boutiques existantes : passées sur Pro, avec des droits acquis.** Elles gardent tout ce qu'elles utilisent aujourd'hui : l'import, et leurs comptes actifs au-delà de 3 s'il y en a. La version actuelle du logiciel devient la version Pro.
> - **L'import Excel/CSV est réservé à Business** pour toutes les autres boutiques.
> - Business ajoutera plus tard l'inventaire physique (lot E), la facture personnalisable (lot E) et le dépôt-réserve (lot F) : ce lot prépare seulement leurs codes de droits.

Branche `feat/offres-pro-business`, depuis `main` à jour.

```
Lot « Offres Pro et Business, droits par offre, Mon abonnement » (branche
feat/offres-pro-business, depuis main à jour). Règles habituelles : ADR au prochain numéro
libre (0132 au moment de l'audit), tests d'abord (rouge puis vert), aucun service payant, ne
jamais ouvrir ni commiter .env, deploy/.env.preprod ni backend/.vercel/. Résumé en français
à la fin, questions ouvertes par AskUserQuestion. Lis d'abord les ADR 0089 (plateforme,
companies.status), 0091 (abonnements, coges_billing, users_plan_limit, essai), 0115 (page
d'accueil et ses gardes de test), 0117 (pages légales), 0118 (inscription), 0125 (licence
sur site), 0130, et deploy/sql/create_billing_role.sql. Migration rétrocompatible (ADR
0083 : ajouts seuls, le code en production l'ignore).

B1. Catalogue des offres (migration)
- Garder les CODES internes `starter`, `business`, `premium` (la licence sur site et
  activate-license les utilisent) ; changer seulement les noms affichés :
  starter -> « Pro » (4 900 FCFA, 3 comptes), business -> « Business » (9 900 FCFA,
  7 comptes), premium -> « Premium », prix NULL (« sur devis »), 10 comptes,
  is_orderable = false.
- Nouvelle colonne plans.annual_price_fcfa (numeric(14,2), NULL = pas de paiement annuel) :
  52 920 pour Pro, 106 920 pour Business, NULL pour Premium. Le montant est écrit en base,
  jamais recalculé à l'affichage ; un test vérifie qu'il vaut 12 x prix x 0,9.
- plans.features devient la SOURCE des droits (plus seulement indicatif). Catalogue fermé
  de codes, documenté dans l'ADR et dans un registre testé :
  * commun (Pro et Business) : sales, purchases, inventory, dashboard, reports_exports,
    product_photos, documents, stock_alerts ;
  * Business seulement : imports, physical_inventory (lot E), invoice_branding (lot E),
    stock_locations (lot F), priority_support ;
  * Premium : tout ce qu'a Business.
  Les codes des lots E et F existent dès maintenant mais ne protègent encore rien.
- Essai : companies_start_trial() pose désormais l'offre `starter` (Pro). Mets à jour les
  textes qui parlent d'un « essai Premium » (e-mails et notifications de l'essai,
  backend/app/cli.py, platform/schemas.py, statistiques de l'administration) : « essai
  gratuit de CoGes Pro ». NE MODIFIE PAS frontend/content/legal/conditions.md (texte
  juridique fourni par le propriétaire) : liste dans le résumé les passages qui citent
  Premium, il les corrigera lui-même.
- Boutiques existantes : toutes les entreprises présentes au moment de la migration (essai,
  payées, suspendues ; licences sur site comprises) passent sur `starter`, sans changer leur
  statut ni leurs dates. Droits acquis :
  * nouvelle colonne subscriptions.extra_features (jsonb, tableau, défaut vide), qui reçoit
    ["imports"] pour chacune d'elles ;
  * nouvelle colonne subscriptions.max_users_override (smallint, NULL par défaut), qui
    reçoit leur nombre de comptes actifs quand il dépasse 3.
  Les deux colonnes sont modifiables seulement par l'administrateur (audit critique), et
  affichées dans l'administration comme « droits acquis ».
- users_plan_limit() : le plafond devient COALESCE(max_users_override, plans.max_users).
  Même verrou, même erreur CG007, mêmes tests de concurrence.

B2. Lire les droits sans ouvrir les tables de la plateforme
- coges_app ne lit toujours AUCUNE table plateforme (ADR 0091). Ajoute une fonction
  SECURITY DEFINER appartenant à coges_billing, par exemple current_plan(), qui rend pour
  l'entreprise du contexte (app.company_id) seulement : code et nom de l'offre, statut de
  l'abonnement, fin d'essai, fin de période payée, plafond de comptes effectif, comptes
  actifs, droits effectifs (features de l'offre + extra_features). EXECUTE à coges_app
  seulement. Tests T36 et T37 mis à jour.
- Côté API, une dépendance require_feature("imports"), à côté de require_permission :
  droit absent -> 403 avec un code distinct, plan_feature_required, et
  details {feature, required_plan: "business"}. Le contrôle est fait par le serveur ;
  l'écran ne fait que refléter. Les droits sont lus une fois par requête.
- Appliquer require_feature("imports") à TOUTES les routes d'import (envoi du fichier ET
  téléchargement du modèle). Les exports restent ouverts à toutes les offres.
- GET /api/v1/auth/me gagne un bloc plan {code, name, status, features} pour que le front
  masque ou verrouille. GET /api/v1/subscription (nouvelle route, permission du gérant à
  proposer dans l'ADR, en principe company:read) rend le détail pour l'écran
  « Mon abonnement ».
- Registre testé : chaque route protégée par un droit d'offre est déclarée, comme le
  registre des permissions ; une route d'import sans require_feature fait échouer la CI.

B3. Paiement déclaré : mois ou année
- POST /api/v1/platform/companies/{id}/payments accepte period_months (1 ou 12, défaut 1).
  12 mois exige l'offre payable à l'année et un montant égal à annual_price_fcfa ; 1 mois,
  un montant égal à price_fcfa (refus 422 sinon, avec le montant attendu). La fin de
  période avance de 1 ou 12 mois (depuis aujourd'hui ou depuis la fin en cours, la plus
  lointaine, comme aujourd'hui). Colonne subscription_payments.period_months (défaut 1).
  Idempotence et audit inchangés.
- Administration : « Enregistrer un paiement » propose « 1 mois » ou « 1 an (-10 %) » avec
  le montant prérempli ; « Changer d'offre » ne propose que les offres vendables, plus
  Premium pour l'administrateur (sur devis) ; la carte « Abonnement » affiche les droits
  acquis, modifiables avec une raison.

B4. Écran « Mon abonnement » (frontend/, gérant)
- Entrée dans Réglages. Contenu en mots simples : l'offre (« CoGes Pro »), le statut
  (« Essai gratuit jusqu'au 25 décembre », « Payé jusqu'au … », « Suspendu »), les comptes
  utilisés (« 2 comptes sur 3 »), ce que contient l'offre, ce qu'ajoute Business, et
  « Comment payer » : en attendant le paiement en ligne (lot D), le numéro Wave / Orange
  Money de CoGes et un bouton WhatsApp prérempli (« Je veux payer CoGes Pro pour 1 mois »),
  avec les deux montants (mois et an, -10 %). Les droits acquis sont affichés (« Import
  inclus pour votre boutique »).
- Sur site (licence, ADR 0125) : l'écran affiche « Licence sur site, offre … », sans
  paiement ni échéance.
- Fonctions verrouillées : l'import reste visible dans la navigation avec un badge
  « Business » ; l'ouvrir montre une carte « Disponible avec Business » et un bouton
  « Passer à Business » (WhatsApp prérempli pour l'instant). Jamais de 403 brut à l'écran :
  le code plan_feature_required est traduit en ce message partout.
- Accessibilité : axe 0 violation, 360 px sans défilement horizontal.

B5. Prix sur la page d'accueil
- vitrine.pricing reçoit les deux offres et Premium sur devis ; une section « Nos offres »
  (deux cartes et une ligne « Plus de 7 personnes ? Premium, sur devis : écrivez-nous »),
  bascule « Par mois / Par an (-10 %) », la liste des fonctions de chaque offre telle que
  dans la décision du propriétaire, et « 30 jours d'essai gratuit sur Pro ».
- Les prix viennent d'UNE seule source partagée avec l'écran « Mon abonnement » (pas de
  montant écrit en double) ; un test compare cette source aux valeurs de la migration.
- Les gardes de vitrine-texte.test.ts (« aucun prix », « aucun % ») sont remplacées, et non
  supprimées : des prix seulement dans la section des offres, et seulement ceux de la
  source ; « 10 % » seulement dans la bascule annuelle.
- [DEMANDER] Libellé du support de Business : « Support prioritaire 24/7 » (la promesse
  de la liste du propriétaire) ou « Support prioritaire » avec les horaires du support.
  Recommandation : ne promettre le 24/7 que si l'équipe peut le tenir.

B6. Tests (rouge d'abord)
- Migration : les codes sont inchangés ; noms, prix et prix annuels attendus ; Premium non
  vendable ; essai d'une nouvelle entreprise sur `starter` ; toutes les entreprises
  existantes sur `starter`, avec ["imports"] et, au-delà de 3 comptes, leur plafond
  conservé ; statuts et dates inchangés.
- Droits : matrice offre x droit (Pro, Pro avec droits acquis, Business, Premium, licence
  sur site) sur toutes les routes d'import, côté API (403 plan_feature_required) ET à
  l'écran ; exports ouverts à tous ; plafond de comptes avec et sans override, en
  concurrence.
- current_plan() : une entreprise ne lit jamais l'offre d'une autre ; coges_app n'a
  toujours aucun droit direct sur plans, subscriptions et subscription_payments (T36).
- Paiement 1 mois et 12 mois, montant faux refusé, idempotence, fin de période.
- Front : « Mon abonnement » (essai, payé, suspendu, sur site, droits acquis), carte
  « Disponible avec Business », section des offres et bascule annuelle, gardes de la vitrine.
- Suite inter-tenant complète verte.

Fin de lot
Suite backend complète, ruff, mypy, make front-check, admin-check, e2e des écrans touchés,
tests de fuite inter-tenant, CI verte. ADR (catalogue des droits, droits acquis, lecture par
current_plan, prix annuels), amendement de l'ADR 0091, openapi.json et types du front,
coges.env.example si besoin, runbook « changer l'offre d'une boutique, enregistrer un
paiement d'un an, accorder ou retirer un droit acquis », CLAUDE.md §8 et table des ADR.

Hors lot, volontairement : relances et suspension (lot C), paiement en ligne Bictorys
(lot D), inventaire physique, facture personnalisable et export des achats (lot E),
dépôt-réserve (lot F).
```

## Ce que le propriétaire fait lui-même

1. **Avant le déploiement**, regarder dans l'administration la liste des boutiques existantes, leurs comptes, et qui utilise l'import : elles garderont tout (droits acquis), mais c'est le moment de les prévenir que leur offre s'appelle désormais « CoGes Pro ».
2. **Corriger les CGU** (`frontend/content/legal/conditions.md`) aux endroits qui parlent d'un essai Premium ou des offres, puis publier une nouvelle version des conditions (l'acceptation sera redemandée). L'agent listera ces passages.
3. **Répondre à la question sur le support de Business** (24/7 ou horaires).
4. **Vérifier en préproduction** : une nouvelle inscription démarre bien un essai Pro sans import ; une boutique existante garde l'import ; un paiement d'un an enregistré dans l'administration avance l'échéance de 12 mois ; la page d'accueil affiche les bons prix.
