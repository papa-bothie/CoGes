# 0036 — Désactivation de l'Intelligence et privilèges de ses tables

- **Date** : 2026-09-25
- **Phase** : 09
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`, questions 4 et 5 du prompt, et question sur
  les privilèges)

## Contexte

Le Diagramme 7 exige qu'une Intelligence coupée laisse CoGes fonctionner et fasse disparaître
proprement les blocs prédictifs, sans dire où vit l'interrupteur. La proposition commerciale
réserve une partie de l'Intelligence à certains paliers, ce que l'architecture V1 ne prévoit pas
(point P8). Enfin le § 8.11 accorde à `coges_app` `SELECT, INSERT, UPDATE` sur toutes les tables,
alors que le Modèle dit de `ml_feature_snapshots` qu'elle n'est « jamais lue par l'application »,
de `forecasts` qu'elle n'est « jamais écrite par un endpoint », et d'`insights.status` qu'il est
« la seule colonne modifiable par l'application ».

## Décision 1 — `settings.intelligence_enabled`, par entreprise

Absent vaut « activée » (comme `tax_enabled`, ADR 0022). Lu par le pipeline (rien n'est calculé ni
écrit, aucun artefact entraîné) et par l'API : `GET /insights`, `/forecasts`,
`/intelligence/summary` répondent 200 avec `enabled: false` ; `PATCH /insights/{id}` répond 409
`intelligence_disabled` ; la métrique 8 rend un `unavailable_reason`. Modifié par
`PATCH /companies/current` (déjà sous audit critique).

## Décision 2 — Aucun palier en V1

Seul le drapeau existe. La facturation par palier reste le point P8, en phase 10.

## Décision 3 — Les règles d'accès deviennent des GRANT (écart assumé, plus strict que § 8.11)

| Rôle | `ml_feature_snapshots` | `forecasts` | `insights` | `notifications` |
|---|---|---|---|---|
| `coges_app` | **aucun** | SELECT | SELECT, UPDATE (`status`, `read_at`, `resolved_at`) | inchangé |
| `coges_analytics` | SELECT, INSERT, UPDATE (`labels`) | SELECT, INSERT, UPDATE | SELECT, INSERT, UPDATE | + INSERT |

Aucun DELETE sur ces tables, pour personne : un insight périmé sort de l'affichage par
`valid_until`, filtré à la lecture ; la purge physique est renvoyée à plus tard. Les deux dates
accompagnent `status` parce que les CHECK croisés du § 8.9 les exigent.

## Conséquences

- T35 devient **structurel** : même un bug de l'API ne pourrait pas lire les features.
- Les tests croisés génériques (T1, T2) tournent sous `coges_app` et ne peuvent pas couvrir
  `ml_feature_snapshots` : `tests/tenancy/test_intelligence_isolation.py` les reprend sous
  `coges_analytics`, et vérifie les privilèges colonne par colonne.
- Un insight critique crée sa notification dans la transaction du pipeline, sous
  `coges_analytics` ; destinataires : les détenteurs de `insights:read` (gérant, comptable).
- Écarté ou résolu, un insight est **clos** pour l'utilisateur (409 `insight_closed`) : le
  rouvrir pourrait heurter l'insight vivant réémis sous la même clé. Le pipeline, lui, rouvre en
  `new` un insight résolu dont le problème réapparaît.
