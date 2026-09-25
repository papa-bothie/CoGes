# 0035 — CoGes Intelligence : bibliothèques, seuil d'historique, artefacts, point-in-time

- **Date** : 2026-09-25
- **Phase** : 09
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`, questions 1 à 3 et 6 du prompt de phase,
  plus la question du point-in-time)

## Contexte

Le Diagramme 7 de l'Architecture décrit un pipeline (collecte → features → modèles versionnés →
inférence → recommandations → tables dédiées) sans nommer d'outil, de seuil d'historique ni de
lieu pour les artefacts de modèle, que le § 6 du Modèle place pourtant « hors base ». Le § 6.2
impose l'anti-fuite (`occurred_at <= as_of`) sans dire ce qu'il advient d'une vente annulée
**après** D.

## Décision 1 — numpy + pandas + statsmodels, dans le worker seulement

Groupe de dépendances `ml` dans `pyproject.toml`, installé par l'image worker
(`uv sync --group ml`) et **jamais** importé par l'API : un test d'architecture importe
`app.main` dans un processus neuf et échoue si numpy, pandas, scipy ou statsmodels sont chargés.
Le paquet `intelligence/pipelines` n'est importé que par les tâches et par la commande
`run-intelligence`. Pas de scikit-learn (aucun modèle V1 ne l'exige), pas de Prophet (lourd,
surdimensionné pour 60 jours d'historique). pandas est une dépendance de statsmodels ; le code
du projet ne l'utilise pas directement.

Les modèles, tous versionnés (`model_name`, `model_version` obligatoires) :

| Modèle | Rôle | Version |
|---|---|---|
| `seasonal_ols` | tendance + jour de semaine, OLS, intervalle de prédiction à 80 % | semaine ISO de production (`2026-W39`) |
| `moving_average_28` | référence, et repli quand l'OLS manque d'observations (< 21 jours) | `1` |
| `zscore_28` | `demand_spike` (z ≥ 3 sur les 28 jours précédents, hors ruptures) | `1` |
| `abc_pareto` | `slow_mover`, sur le chiffre d'affaires 28 jours **nommé** | `1` |

Les jours de rupture (stock du soir nul alors que le journal connaît le produit) sont exclus de
l'ajustement : demande **censurée**, pas demande nulle (§ 6.2).

## Décision 2 — Seuil : 28 jours depuis la première vente et 5 jours vendus sur 60

En dessous, **aucune** prévision et un insight `insufficient_history` (ADR 0037). Les seuils
sont écrits dans l'évidence de chaque insight.

## Décision 3 — Artefacts JSON sur le volume du worker

`COGES_ML_ARTIFACTS_DIR/<company_id>/<model_name>/<model_version>.json`, écrit de façon atomique.
JSON et jamais pickle : un artefact se relit sans exécuter de code. Le chemin est recopié dans
`forecasts.metadata.artifact_path`. Volume `ml-artifacts` dans `deploy/docker-compose.worker.yml`.
Un artefact perdu se réentraîne à la volée à la première inférence de la semaine.

## Décision 4 — Point-in-time strict, sur les horodatages métier

À `as_of = D`, une vente compte si `sold_at < minuit(D+1)` et si elle est confirmée **ou**
annulée après cette borne ; un retour n'est déduit que si `returned_at` précède la borne ; le
stock est reconstitué depuis `inventory_movements.occurred_at`. Les photographies
(`ml_feature_snapshots`) sont écrites une fois (`ON CONFLICT DO NOTHING`), seuls les labels
(réalisé des 7 jours suivants, pour le backtest) se complètent plus tard. L'inférence ne lit que
ces photographies.

Le temps retenu est celui du **métier** (`sold_at`, `occurred_at`) et non celui de
l'enregistrement : c'est ce qu'écrit le § 6.2, et c'est ce qui permet de rejouer un historique
importé. Conséquence assumée : un mouvement antidaté reste une fuite possible, bornée aux 48 h de
l'ADR 0015.

## Conséquences

- Façades ajoutées : `sales_service.daily_product_sales_as_of`, `first_sale_days_as_of`,
  `inventory_service.daily_on_hand` (même reconstitution que `average_on_hand`, factorisée),
  `products_service.active_summaries`.
- Un produit que le journal ne connaît pas encore à D a un stock **inconnu**, pas nul : sans cela,
  tout article réceptionné après D serait annoncé en rupture.
- Planification : features 03 h 30, entraînement le lundi 03 h 45, inférence 04 h 30 (UTC).
- Le délai de paiement n'est pas une feature produit (`ml_feature_snapshots.product_id` est
  `NOT NULL`) : il vit dans l'évidence de `debt_overdue`.
