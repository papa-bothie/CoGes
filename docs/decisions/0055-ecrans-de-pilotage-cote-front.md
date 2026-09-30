# 0055 — Écrans de pilotage côté front : finance, analytics, intelligence, paramètres

- **Date** : 2026-09-30
- **Phase** : 13
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte

La phase 13 branche les écrans 7 à 10 du prototype : Finance, Analytics, CoGes Intelligence,
Paramètres, et le panneau des notifications. Ils affichent des chiffres **déjà calculés par le
serveur** ; toute métrique est nommée, toute prévision datée et qualifiée (Diagramme 7). Le prompt
laissait cinq choix ouverts ; les trous d'API rencontrés en route sont tranchés par les ADR 0053
et 0054.

## Décisions

1. **Cartes d'Intelligence compactes** en grille (type, sévérité, titre, métrique et valeur, date
   de calcul, confiance), détail dans un **panneau latéral** : texte, `ForecastMeta` (métrique,
   date de calcul, modèle et version — « Règle de gestion » quand aucun modèle —, incertitude),
   éléments du calcul et seuils de l'`evidence`, lien vers l'élément, changements de statut.
   L'`evidence` ne portant aucune série, le **mini-graphique** est la prévision du produit
   concerné (valeur et bande d'incertitude sur l'horizon), lue sur `GET /forecasts`.
2. **Sélecteur de métrique** en liste déroulante ; la définition de la métrique choisie reste
   affichée, chaque option porte la sienne au survol, une infobulle rappelle qu'aucune métrique
   n'est combinée. Le titre, la phrase de tête (« … génère le plus fort chiffre d'affaires … »)
   et **chaque ligne** nomment la métrique renvoyée par l'API (`metric_label`).
3. **Période commune** dans l'URL (`?period=7d|30d|90d|month|custom&from&to`), bornes en jours
   calendaires **dans le fuseau de l'entreprise** ; absente de l'onglet Dettes, qui est un état.
4. **Règlement réparti** : un versement sur les dettes ouvertes d'un même tiers, préremplissage
   « échéances les plus anciennes d'abord » (`lib/allocation.ts`), modifiable ; le serveur juge
   chaque affectation (409 sur la ligne concernée).
5. **Journal d'activité** en lecture, gérant et comptable (ADR 0053), filtres période, utilisateur,
   action, entité ; détail avant / après champ par champ.

Règles transverses appliquées :

- **Aucun calcul financier** dans le navigateur. Deux exceptions d'affichage, jamais décisives :
  le préremplissage d'une répartition et le reste à régler d'une dépense proposé dans le
  dialogue de règlement (`subtractDecimal`, sans `float`). Les compteurs « Anomalies » additionnent
  des nombres d'insights, pas des montants.
- `Idempotency-Key` gardée jusqu'au succès sur paiements, règlements, annulations, dettes et
  dépenses (payées ou non).
- Libellés interdits vérifiés par un test Vitest (`meilleur`, `top produit`, `score`,
  `en direct`) sur les textes d'Analytics, d'Intelligence et des prévisions.
- Intelligence désactivée : l'écran l'explique, le bloc du tableau de bord **disparaît** (capture
  vérifiée en coupant puis rétablissant le réglage).
- Notifications : panneau depuis la cloche, lien vers l'élément quand `data` porte son identifiant
  (produit, vente, type d'insight), ouverture = lecture ; page complète filtrable « non lues ».

## Écarts par rapport au prototype

| Écart | Raison |
|---|---|
| Cartes d'Intelligence compactes + panneau | Défaut du prototype (cartes trop hautes), décision 1 |
| Mini-graphique = prévision du produit, pas l'`evidence` | L'`evidence` ne contient aucune série ; les insights hors produit montrent faits et seuils |
| Bloc Intelligence ajouté au tableau de bord | Donne un objet à la règle « les blocs prédictifs disparaissent proprement » |
| Devise en lecture seule | V1 mono-devise (ADR 0054) |
| « Seuils par défaut » = un seuil d'alerte par défaut | Seul seuil que le modèle connaisse (`reorder_point`), appliqué par le serveur (ADR 0054) |
| Rôles système non modifiables à l'écran | Le serveur refuse ; un besoin particulier passe par un rôle personnalisé |
| Alerte « dette échue » menant à la liste des dettes échues, pas à la dette | L'alerte ne porte pas l'identifiant du tiers |
| Textes des alertes de stock avec un point décimal (« 1.000 ») | Rédigés par le worker ; à reprendre côté serveur en phase 14 |
| Couleur `chart-1` légèrement sous le plancher de saturation en clair | Jetons du prototype figés (ADR 0046) ; séparation des séries validée (ΔE ≥ 23) |
| Police, densité, polish visuel | Phase 14 (Impeccable) |

## Conséquences

- Composants partagés : `PeriodPicker`/`usePeriod`, `CashFlowChart`, `ReasonDialog`,
  `components/forecast/` (`ForecastMeta`, `ForecastBandChart`, `ProductForecast`,
  `IntelligenceSummaryCard`), `NotificationItem` ; `lib/metrics.ts`, `lib/intelligence.ts`,
  `lib/permission-labels.ts`, `lib/notifications.ts`.
- Parcours Playwright (`e2e/pilotage.spec.ts`) : paiement réparti sur deux dettes puis soldes
  relus ; changement de métrique et libellé sur chaque ligne ; insight écarté ; vendeur sans
  Paramètres à l'écran **et** 403 sur cinq routes. Captures : `docs/design/captures/phase-13/`.
