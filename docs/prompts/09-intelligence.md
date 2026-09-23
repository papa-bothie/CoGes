# Phase 09 — CoGes Intelligence (V1 simple)

---

Tu es l'agent de développement du projet **CoGes**. Nous démarrons la **phase 09 : CoGes
Intelligence**. C'est une couche **strictement séparée** : elle lit des données déjà agrégées,
écrit **uniquement** dans ses propres tables, ne bloque jamais une opération et peut être désactivée
sans rien casser. L'API ne fait que **lire** des résultats déjà calculés.

## 0. Protocole

1. Lis `CLAUDE.md` (phase 08 ✅ exigée) et les ADR.
2. Lis :
   - Architecture : Diagramme 7 et annexe A.7 (pipeline 01 → 09) ; les **8 métriques** et le
     tableau CORRECT / INTERDIT ; règles d'affichage des prévisions (date, modèle, incertitude,
     données insuffisantes, désactivation) (≈509-585) ; décisions 11, 12, 13.
   - Modèle : § 4.11 (`forecasts`), § 4.12 (`insights`, frontière avec `notifications`) ; § 6 et
     § 6.2 (**anti-fuite temporelle**, séries denses, signal de rupture) ; SQL § 8.9 ; § 10 tests
     **T33–T35**.
3. Pose les questions du § 2 avec `AskUserQuestion` avant de coder.
4. Plan → feu vert → exécution → vérification → clôture.

## 1. Objectif

Produire, chaque nuit et pour chaque entreprise, des features figées, des prévisions simples
(demande, date de rupture), des anomalies simples et des recommandations explicables, toutes
persistées avec leur métrique, leur valeur, leur date, leur modèle et leur incertitude, puis les
servir en lecture seule.

## 2. Questions à me poser (AskUserQuestion)

1. **Bibliothèques** : pandas + statsmodels (régression saisonnière) + numpy, sans scikit-learn en
   V1 (Recommandé : les modèles prévus sont simples) / scikit-learn en plus / Prophet (lourd,
   déconseillé en V1).
2. **Seuil minimal d'historique** pour produire une prévision produit : au moins 28 jours depuis la
   première vente **et** au moins 5 jours avec des ventes sur les 60 derniers jours (Recommandé) /
   autre seuil. En dessous : insight « données insuffisantes », jamais une valeur.
3. **Stockage des artefacts de modèle** (hors base, § 6) : volume du conteneur worker en V1, avec le
   chemin et la version enregistrés dans `forecasts.metadata` (Recommandé) / stockage objet
   (S3-compatible, me demander lequel).
4. **Désactivation** : drapeau `settings.intelligence_enabled` par entreprise, lu par le pipeline
   (pas de calcul) et par l'API (blocs masqués, 200 avec `enabled: false`) (Recommandé) / variable
   d'environnement globale uniquement / les deux.
5. **Paliers commerciaux** : la proposition de tarification réserve une partie de l'Intelligence à
   certains paliers, ce que l'architecture V1 ne prévoit pas. Ignorer en V1 et garder seulement le
   drapeau de la question 4 (Recommandé) / ajouter un niveau `alerts_only | full` (écart à
   documenter).
6. **Insights à produire en V1** parmi l'ENUM : `stockout_risk`, `slow_mover`, `demand_spike`,
   `margin_drop`, `debt_overdue` (Recommandé : couvrent les exemples du prototype) / ajouter
   `expense_anomaly`, `cash_shortfall` / tous, y compris `cashier_anomaly`.

## 3. Périmètre

**Migration `0009_intelligence`** : `ml_feature_snapshots`, `forecasts` (`UNIQUE NULLS NOT DISTINCT`),
`insights` (index unique partiel sur `dedupe_key WHERE status <> 'dismissed'`), CHECK, index et
RLS du § 8.9.

**Pipeline** (`modules/intelligence/{features,models,pipelines}` + tâches `ml_features.py`,
`ml_train.py`, `ml_infer.py`, planifiées par beat, **une entreprise à la fois avec son contexte**)
- 02-03 collecte incrémentale et préparation : ventes annulées exclues, calendrier dense (jours
  sans vente = 0), stock reconstitué **à la date** pour distinguer faible demande et rupture.
- 04 features par `as_of` (j / 7 j / 28 j, saisonnalité hebdomadaire, marge par produit, rotation,
  délai de paiement, jours de couverture) écrites **une seule fois** par `as_of` (anti-fuite :
  `occurred_at <= as_of`).
- 05 modèles versionnés (hebdomadaire) : moyenne mobile de référence, régression saisonnière,
  z-score pour les anomalies, ABC-Pareto ; `model_name` et `model_version` obligatoires.
- 06 inférence quotidienne ⇒ `forecasts` (`demand_qty`, `stockout_date`) avec `yhat_lower` et
  `yhat_upper` quand disponibles, en `ON CONFLICT DO UPDATE`.
- 07 insights ⇒ `insights` avec `evidence` (séries, seuils, écarts, période) qui permet de justifier
  l'affichage sans recalcul ; `dedupe_key` stable (ex. `stockout_risk:<product_id>:2026-W39`) ; un
  insight `critical` crée une notification (l'inverse n'existe pas).
- Métrique 8 « potentiel futur estimé » : maintenant disponible pour `/analytics/products`.

**Serving (lecture seule, `serving.py`)**
- `GET /api/v1/insights?status=&severity=&type=` ; `PATCH /api/v1/insights/{id}` (seule
  `status` est modifiable : `read`, `acknowledged`, `dismissed`, `resolved`).
- `GET /api/v1/forecasts?product_id=&type=` ; `GET /api/v1/intelligence/summary` (compteurs par
  type, nombre de produits aux données insuffisantes).
- Chaque élément renvoyé contient : `metric_name` (libellé exact de l'une des 8 métriques ou de la
  mesure prévue), `value`, `computed_at`, `model_name`, `model_version`, `uncertainty` (intervalle
  ou qualificatif), ou `insufficient_data: true`.

**Tests**
- **T33** rejeu du pipeline sur le même `as_of` ⇒ mise à jour, pas de doublon ; **T34** insight
  `dismissed` puis réémission de la même `dedupe_key` ⇒ acceptée ; **T35** trace SQL des endpoints
  de prévision ⇒ aucune lecture de `ml_feature_snapshots`, aucun calcul : seulement `forecasts` et
  `insights` par index.
- Anti-fuite : une feature à `as_of = D` n'utilise aucune donnée postérieure à D (test avec un
  retour enregistré après D).
- Données insuffisantes : produit sous le seuil ⇒ aucun forecast, un insight explicite.
- Désactivation : pipeline arrêté et API qui répond `enabled: false`, le reste de CoGes fonctionne.
- Contrôle de libellé : aucune chaîne « meilleur produit », « best product » ou « top » sans métrique
  dans les titres générés (test sur les gabarits).
- Isolation : T1 étendu à `forecasts`, `insights` et `ml_feature_snapshots` ; T37 vert.

**Hors périmètre** : ML avancé, agents conversationnels, entraînement dans l'API, tout effet sur
les tables transactionnelles.

## 4. Règles à respecter

- Le pipeline n'écrit **que** dans `ml_feature_snapshots`, `forecasts`, `insights` et
  `notifications`.
- Jamais de « meilleur produit » : toujours « le produit générant la plus forte <métrique> sur
  <période> ».
- Jamais « en direct » : toute prévision affiche sa date de production.

## 5. Vérification

Sur le jeu `make seed-demo` : lance le pipeline complet, montre 3 insights (dont un « données
insuffisantes »), un forecast avec son intervalle, et la réponse de `/intelligence/summary`.

## 6. Clôture

ADR (bibliothèques, seuils, artefacts, désactivation) ; `CLAUDE.md` mis à jour ; résumé.
