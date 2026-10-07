# 0061 — Le jour en cours est calculé en direct

- **Date** : 2026-10-07
- **Phase** : 15 (lot 0, bug B1)
- **Statut** : acceptée — amende l'écart 1 de l'ADR 0034
- **Décideur** : utilisateur (prompt de phase 15, retours d'usage réels)

## Contexte
Le CA du jour, le CA du mois, la marge et la courbe du tableau de bord ne bougeaient pas
après une vente. `dashboard._compose` lisait tout dans `daily_sales_facts`, que seule la
tâche Celery `analytics.rebuild_sale_day` reconstruit. Cette tâche ne reçoit
`sale.confirmed` que si le relais d'outbox **et** le worker tournent. En local, le relais
n'était pas lancé ; en préproduction, tout dépend de la zone B sur le poste du gérant. Le
cache Redis de 60 s, lui aussi vidé par le worker, ajoutait son propre délai.

Pendant ce temps, le nombre de ventes et « Dernières ventes », lus sur `sales`, étaient
justes : l'écart sautait aux yeux.

L'ADR 0034 (écart 1) avait écarté le calcul direct du jour en cours, pour ne pas remettre
un parcours de `sale_items` dans la requête HTTP. En usage, le retard s'est révélé plus
grave que ce coût.

## Options envisagées
1. **Jour en cours en direct, passé sur les faits (retenue).** Le parcours est borné à un
   seul jour d'une seule entreprise, sur l'index `(company_id, status, sold_at)`.
2. Tout recalculer en direct : le mois et 30 jours de courbe dans la requête, ce qui ne
   tient plus sous 200 ms sur une boutique active.
3. Garder les faits et demander que le relais tourne : c'est la situation qui a produit
   le bug.

## Décision
- **Aujourd'hui** : CA net, marge et nombre de ventes viennent de
  `sales_service.revenue_totals` sur les bornes du jour, dans le fuseau de l'entreprise.
  Ce sont les définitions du § 4.10 : coût figé sur la ligne, retours rattachés au jour de
  la vente, ventes annulées et brouillons exclus. C'est la façade que la réconciliation T32
  utilise déjà.
- **Le mois et la courbe** : les faits **jusqu'à hier**, plus le jour en direct.
- **Invalidation synchrone** : `app.core.tenancy.on_commit` joue des rappels **après** le
  COMMIT de la transaction du cas d'usage, jamais après un ROLLBACK. Un échec y est
  journalisé, jamais propagé. `outbox.emit` y inscrit le vidage de la clé `dashboard` : ce
  sont exactement les types d'événements qui vident déjà le tableau de bord côté worker.
  L'abandon de créance, qui n'émet rien (ADR 0029), l'inscrit lui-même. La clé
  (`cache.DASHBOARD_KEY`) vit dans `core`, parce que les modules qui écrivent ne peuvent
  pas importer Dashboard (bande E).
- **Le retard est visible** : si l'événement le plus ancien de l'outbox attend depuis plus
  de deux minutes (`GET /system/outbox`, champ `oldest_pending_at`), le tableau de bord du
  gérant affiche un bandeau neutre : « Certains chiffres se mettent à jour, patientez une
  minute. »
- **`make dev`** lance API, worker, relais et front ensemble (`Procfile.dev`, honcho en
  dépendance de développement).

## Conséquences
- Le CA du jour ne dépend plus ni du relais, ni du worker, ni du TTL. Les jours passés,
  eux, en dépendent toujours, ainsi que les alertes et l'Intelligence.
- Une vente d'hier retournée aujourd'hui n'apparaît dans hier qu'après la reconstruction
  des faits. C'est assumé, et le bandeau le signale si elle tarde.
- Le worker garde son invalidation, qui sert de filet de sécurité.
- Tests : `test_dashboard_live_today.py` (vente, annulation, retour et cache, sans aucune
  reconstruction) et `test_after_commit.py`. La latence reste mesurée par `make test-perf`.
