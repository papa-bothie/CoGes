# Phase 08 — Asynchrone, notifications, agrégats analytiques, tableau de bord

---

Tu es l'agent de développement du projet **CoGes**. Nous démarrons la **phase 08 : le chemin
asynchrone et la bande E Restitution** (hors Intelligence). Tout ce qui se passe **après COMMIT**
est construit ici : relais de l'outbox, workers Celery, notifications, audit secondaire, agrégats
`daily_sales_facts`, tableau de bord et analytics.

## 0. Protocole

1. Lis `CLAUDE.md` (phase 07 ✅ exigée) et les ADR.
2. Lis :
   - Architecture : Diagramme 1 (chemin asynchrone) ; Diagramme 2 (zone B Docker, aucun appel
     entrant vers Vercel) ; audit secondaire (≈412) ; modules Dashboard, Analytics, Notifications
     (≈330-345) ; performance et « où s'exécute quoi » (≈702) ; décisions 04, 05, 14 ; Diagramme
     10 (`workers/`).
   - Modèle : § 4.10 (`daily_sales_facts`, définitions exactes) ; § 6 et § 6.1 (reconstruction par
     plage réaffectée, **pré-agrégation des retours**) ; SQL § 8.8 (`notifications`), § 8.9
     (couche analytique) ; § 10 tests **T29–T32**, **T40** ; § 12.1 point 3 (fenêtre de
     reconstruction).
3. Pose les questions du § 2 avec `AskUserQuestion` avant de coder.
4. Plan → feu vert → exécution → vérification → clôture.

## 1. Objectif

Chaque événement écrit dans l'outbox est publié **au moins une fois** après COMMIT et traité
**exactement une fois en effet** par des consommateurs idempotents. Le tableau de bord se lit en
moins de 200 ms sur des agrégats déjà calculés.

## 2. Questions à me poser (AskUserQuestion)

1. **Relais de l'outbox** : processus dans le conteneur worker qui lit `business_events` non
   publiés avec `FOR UPDATE SKIP LOCKED` par lots, publie dans Redis (Celery), marque
   `published_at` et incrémente `attempts` (≤ 10) (Recommandé) / `LISTEN/NOTIFY` + balayage de
   secours / tâche Celery beat toutes les N secondes.
   ⚠️ Le relais lit **toutes** les entreprises : c'est le seul composant multi-tenant. Il doit
   tourner avec un rôle dédié `coges_relay`, qui lit et met à jour **uniquement**
   `business_events`, et une boucle explicite par tenant ; les tâches métier qu'il déclenche posent
   ensuite leur propre contexte. D'accord avec ce modèle ?
2. **Idempotence des consommateurs** : table `processed_events (consumer, event_id)` avec unicité,
   écrite dans la transaction du consommateur (Recommandé) / clés Redis avec TTL.
3. **File de rebut** : après 10 tentatives ⇒ événement marqué en échec + log d'alerte + compteur
   exposé dans un endpoint d'administration (Recommandé) / file Redis séparée.
4. **Canal e-mail des notifications** : in-app seulement en V1, e-mail préparé derrière une
   interface (Recommandé : pas de fournisseur à choisir maintenant) / fournisseur SMTP ou API (me
   demander lequel).
5. **Calcul des 8 métriques produit** (Architecture, Diagramme 7) : les métriques 1 à 7 (CA, marge,
   quantité, fréquence, rotation, vélocité, évolution de la demande) sont calculées à la lecture
   depuis `daily_sales_facts` et `product_stock`, avec index et cache court par tenant ; la
   métrique 8 (potentiel futur) vient des `forecasts` en phase 09 (Recommandé) / table de
   métriques précalculée chaque nuit.
6. **Rotation du stock** : stock moyen = moyenne des quantités de fin de journée reconstituées
   depuis le journal sur la période (Recommandé : exact) / (stock début + stock fin) / 2
   (approximation, à afficher comme telle).
7. **Cache du tableau de bord** : Redis, clé par tenant, TTL court (60 s) + invalidation par
   événement (Recommandé) / pas de cache au début.

## 3. Périmètre

**Infrastructure** : `workers/celery_app.py`, `workers/beat.py`, `deploy/docker-compose.worker.yml`
(worker, beat, relais), `Dockerfile.worker` qui réutilise **le même code** que l'API (autre point
d'entrée). Chaque tâche prend un `company_id` et ouvre sa transaction avec **son** contexte tenant
(Diagramme 8) : aucune tâche « multi-tenant » sans boucle explicite.

**Tâches**
- `outbox_relay.py` (réponse 1), avec reprise et back-off exponentiel.
- `analytics.py` : reconstruction de `daily_sales_facts` **par plage de jours réaffectée**,
  déduite des événements depuis le dernier passage, en DELETE/INSERT dans une transaction par
  entreprise, **avec la requête du § 6.1 copiée à l'identique** (CTE `retours` pré-agrégée par
  `sale_item_id`) ; purge des faits devenus vides ; invalidation du cache.
- `notifications.py` : `stock_low` / `stock_out` (sur `stock.updated`), `debt_due` (job
  quotidien), `sale_cancelled` ; destinataires selon le rôle ; déduplication par fenêtre.
- Audit secondaire : connexions, exports, consultations sensibles (**jamais** la preuve d'une
  opération critique).
- `reconcile.py` (beat) : `rebuild_product_stock` chaque nuit par entreprise (tâche de la phase
  04) ; contrôle hebdomadaire **T32** (écart `net_revenue` ≤ 0,01 sur 90 jours, sinon alerte) ;
  création des partitions `audit_logs` du mois suivant.

**API (lecture seule)**
- `GET /api/v1/dashboard` : CA du jour et du mois, marge estimée du mois, ventes du jour, créances
  en cours, nombre d'alertes de stock, CA sur 30 jours, 5 dernières ventes, alertes actives.
- `GET /api/v1/analytics/products?metric=<une des 8>&from=&to=&limit=10` : classement **pour une
  seule métrique**, dont le nom figure dans la réponse ; métrique 8 ⇒ « disponible en phase 09 »
  tant que les forecasts n'existent pas. `GET /api/v1/analytics/timeseries?measure=revenue|margin`.
- `GET/PATCH /api/v1/notifications` (liste, marquer comme lue), compteur non lu.

**Tests**
- **T29** une ligne avec 3 retours partiels ⇒ mêmes `qty_sold`, `gross_revenue`,
  `discount_total`, `cogs_gross` et `sale_count` que sans retour ; **T30** reconstruction de la même
  plage deux fois ⇒ identique ; **T31** vente annulée après construction ⇒ fait purgé ; **T32**
  égalité à 0,01 près avec le calcul direct sur 90 jours ; **T40** crash simulé après COMMIT et
  avant publication ⇒ événement toujours présent et publié à la reprise.
- Consommateur rejoué deux fois ⇒ un seul effet ; tâche d'une entreprise A ⇒ aucune écriture chez B ;
  `daily_sales_facts` couvert par la RLS (T1 étendu, T37 vert).
- Performance : `GET /dashboard` < 200 ms sur un jeu de données seed réaliste (fournis un script
  `make seed-demo` : environ 20 produits, 50 ventes sur 60 jours, comme le prototype).

**Hors périmètre** : forecasts, insights, ML (phase 09).

## 4. Règles à respecter

- Aucun traitement long dans une requête HTTP ; l'API ne fait que lire des agrégats.
- Aucune nouvelle notation d'événement ; aucun appel des workers vers l'API.
- Toute métrique affichée porte son nom ; aucun score combiné.

## 5. Vérification

`make up && make worker` : une vente confirmée produit, en quelques secondes, la mise à jour des
agrégats, une notification de stock bas si le seuil est franchi et un événement `published_at`
renseigné. Montre les logs.

## 6. Clôture

ADR (relais, rôle `coges_relay`, idempotence, métriques) ; `CLAUDE.md` mis à jour ; résumé.
