# 0037 — Écarts assumés de la phase 09

- **Date** : 2026-09-25
- **Phase** : 09
- **Statut** : acceptée
- **Décideur** : utilisateur pour les écarts 1 et 2 ; les autres découlent des documents et sont
  consignés parce qu'ils se voient dans le code

## Écart 1 — `insufficient_history` rejoint l'ENUM `insight_type`

Le § 8.1 n'a aucune valeur pour « données insuffisantes », or l'API ne calcule rien : elle ne
peut pas déduire elle-même qu'un produit est sous le seuil. La révision 0011 ajoute la valeur ;
un insight `info` par produit sous le seuil (`insufficient_history:<product_id>`, sans semaine,
sans `valid_until`), **résolu par le pipeline** quand le seuil est atteint. Le downgrade recrée le
type tel que la révision 0001 l'a posé.

## Écart 2 — `estimators/` au lieu de `models/`

Le Diagramme 10 place les modèles ML dans `intelligence/models/`, le gabarit de l'ADR 0010
réserve `models.py` aux tables. Les deux ne pouvant coexister, le dossier ML s'appelle
`estimators/`.

## Écart 3 — Numéro de révision

Le prompt nomme la migration `0009_intelligence` ; `0009` était déjà prise par la finance. La
révision est `0011_intelligence`.

## Écart 4 — Horizons et forme des prévisions

- `demand_qty` : une ligne par jour de J+1 à J+14.
- `stockout_date` : une ligne quand la demande cumulée prévue atteint le stock du soir de D dans
  les 28 jours ; `yhat` = jours avant rupture, bornes en jours (demande haute ⇒ rupture au plus
  tôt, demande basse ⇒ au plus tard ou `NULL` hors horizon), `horizon_date = as_of + yhat`.
  Déterministe pour un même `as_of` et une même version, donc idempotent (T33).
- Le qualificatif d'incertitude (`faible`, `moyenne`, `élevée`) est figé par le pipeline dans
  `metadata`/`evidence`, jamais recalculé par l'API.
- Le nom du produit est recopié dans `forecasts.metadata.product_name` : l'écran de prévision n'a
  ainsi aucune raison de lire `products` (T35).

## Écart 5 — Métrique 8 : champs additifs

`GET /analytics/products?metric=future_potential` lit `forecasts` (somme des `yhat` J+1..J+14 du
dernier `as_of`). La réponse gagne des champs **optionnels** — `computed_at`, `forecast_as_of`,
`horizon_days`, et par ligne `lower`, `upper`, `model_name`, `model_version` — exigés par la
décision 13. La période demandée ne s'applique pas à un potentiel futur ; la réponse le dit par
`forecast_as_of`. Sans prévision : « Données insuffisantes » ; Intelligence coupée : message dédié.

## Écart 6 — Clé de déduplication et péremption

`<type>:<entité>:<semaine ISO>` (jour pour `demand_spike`), `valid_until` = fin de la semaine
suivant `as_of`. La version d'un modèle hebdomadaire est la semaine ISO de `as_of + 1` (le jour où
le pipeline tourne), pour que l'entraînement du lundi et les inférences de la semaine partagent la
même version.
