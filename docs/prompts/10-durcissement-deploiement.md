# Phase 10 — Annulation de paiement, puis import/export, durcissement, déploiement du backend

---

Tu es l'agent de développement du projet **CoGes**. Nous démarrons la **phase 10 : mise en état
de production du backend**. Elle comporte **deux temps, dans cet ordre** :

- **Temps A (prioritaire, livré et mergé à part)** : l'annulation d'un paiement erroné, laissée
  ouverte par l'ADR 0031 (décision 4). C'est la seule règle métier nouvelle de la phase.
- **Temps B** : l'import/export prévu en V1, le durcissement de la sécurité et de
  l'observabilité, le déploiement selon le Diagramme 2, et la CI bloquante sur les tests
  d'intégrité.

Ne commence **pas** le temps B tant que le temps A n'est pas terminé, testé et mergé.

---

## Temps A — Annulation d'un paiement erroné (contre-écriture)

### A.0 Contexte

Aujourd'hui, un caissier qui saisit 50 000 au lieu de 5 000 n'a **aucun** moyen de corriger :
`payments` n'a ni statut ni suppression logique (§ 8.6), `coges_app` n'a pas `DELETE`, et
`payments:update` / `payments:cancel` existent au catalogue sans endpoint (ADR 0031). C'est
bloquant pour une mise en production réelle.

Principe imposé, identique au mouvement inverse du stock (phase 04, ADR 0017) : **on n'efface
jamais, on contre-passe**. Le paiement d'origine reste intact et lisible ; une écriture
d'annulation le neutralise, et l'on corrige ensuite en saisissant le bon paiement.

### A.1 À lire

`CLAUDE.md`, ADR 0017 (inverse de stock), 0024 (compensation `offset`), 0027 (idempotence), 0029
(dettes), 0031 (décision 4) ; Modèle § 4.9 (`payments`), § 5.5 (dettes et paiements), SQL § 8.6
et § 8.7 (`allocation_check`, `debt_rollup`, `sale_paid_rollup`, `refund_rollup`) ; migrations
0006 à 0009.

### A.2 Questions à me poser (AskUserQuestion) avant de coder

1. **Représentation de l'annulation** : nouvelle colonne `payments.reversal_of_payment_id`
   (FK composite auto-référente, `UNIQUE (company_id, reversal_of_payment_id)` pour qu'un
   paiement ne s'annule qu'une fois, `CHECK` : direction opposée et même montant que l'origine),
   sur le modèle exact de `inventory_movements.reversal_of_movement_id` (Recommandé) / colonne
   `cancelled_at` + motif sur le paiement d'origine (modifie une écriture financière : déconseillé) /
   autre proposition.
2. **Effet sur les lettrages** : l'annulation crée des allocations **négatives**… impossible
   (`CHECK amount > 0`). Propose-moi la mécanique exacte pour que la dette remonte (et que
   `sales.paid_total`, `sale_returns.refunded_total` reviennent en arrière le cas échéant) **sans
   supprimer ni modifier** les lignes d'allocation d'origine. Par exemple : les triggers de rollup
   ignorent les allocations dont le paiement est annulé, et `debt_rollup` repasse une dette
   `paid` en `partially_paid` / `open` (`closed_at` remis à NULL). Montre-moi le SQL avant de
   l'écrire. C'est le point le plus délicat du temps A.
3. **Périmètre** : annulation d'un encaissement client, d'un décaissement fournisseur ou de
   dépense, et d'un remboursement de retour (Recommandé : tous, même mécanique) / encaissements
   seulement en V1. Les compensations `offset` (ADR 0024) : annulables par paire, en une seule
   opération (Recommandé) / non annulables.
4. **Délai** : annulation possible sans limite de date, avec motif obligatoire (Recommandé) /
   limitée à N jours.
5. **Droits** : gérant seul, `payments:cancel` (Recommandé, cohérent avec `sales:cancel`) / gérant
   et comptable.
6. **Correction** : pas d'endpoint « modifier un paiement » ; la correction = annulation + nouvelle
   saisie, en deux appels (Recommandé) / un endpoint qui fait les deux dans une transaction.

### A.3 Périmètre

- Migration dédiée (numéro suivant), réversible, avec la colonne et les contraintes retenues,
  les triggers de rollup adaptés (copiés depuis leur dernière version puis modifiés, avec
  commentaire de l'écart), les SQLSTATE applicatifs nommés (`CG05x`) pour chaque refus.
- `POST /api/v1/payments/{id}/cancel` : motif obligatoire, `Idempotency-Key` obligatoire, permission
  `payments:cancel`, **audit critique** (valeur avant / après : paiement, dettes et soldes touchés),
  événement dans l'outbox (demande-moi si un nouveau type d'événement est nécessaire : la liste des
  9 est fermée, ajouter `payment.cancelled` est une décision à valider).
- Refus nommés : paiement déjà annulé (`payment_already_cancelled`, garanti par l'unicité en base),
  annulation d'une annulation (`cannot_cancel_a_reversal`), paiement d'un autre tenant ⇒ 404.
- Vue « trésorerie » (phase 07) et agrégats (phase 08) : un paiement annulé et son annulation
  s'annulent exactement ; vérifie et teste que les totaux reviennent à l'état antérieur.
- Lecture : un paiement renvoie `cancelled: true`, la date, le motif et l'id de l'annulation.

### A.4 Tests (base réelle, en `coges_app`)

- Encaissement de 50 000 sur une dette de 60 000, annulé ⇒ dette revenue à 60 000 et `open`,
  trésorerie revenue à l'identique, audit présent.
- Dette soldée (`paid`, `closed_at` renseigné) dont on annule le dernier paiement ⇒
  `partially_paid`, `closed_at` NULL.
- Vente payée comptant dont on annule l'encaissement ⇒ `paid_total` revient à 0.
- Remboursement de retour annulé ⇒ `refunded_total` et `refund_status` reviennent en arrière.
- Double annulation ⇒ violation d'unicité traduite en `payment_already_cancelled`, aucun effet.
- **Concurrence** : deux annulations simultanées du même paiement ⇒ une seule passe.
- **Concurrence** : annulation et nouveau paiement simultanés sur la même dette ⇒ solde final exact.
- Aucune ligne de `payments` ni de `payment_allocations` n'est modifiée ni supprimée (comparaison
  avant / après sur les colonnes d'origine).
- T25 à T28 et les tests de trésorerie de la phase 07 restent verts.

### A.5 Clôture du temps A

ADR dédiée ; `CLAUDE.md` mis à jour (décision au § 9) ; `make lint && make test` ; commit ; merge
dans `main`. Résumé à l'utilisateur, **puis seulement** passage au temps B.

---

## Temps B — Import/export, durcissement, déploiement

## 0. Protocole

1. Lis `CLAUDE.md` (phase 09 ✅ et temps A ✅ exigés) et tous les ADR.
2. Lis :
   - Architecture : Diagramme 2 (zones Vercel / Docker, règle d'affectation, contraintes acceptées) ;
     module Import/Export (≈340) ; Diagramme 8, étape 4 (pooling en mode transaction) ; tests de
     fuite ; performance ; décisions 02, 06, 07, 14, 16, 17 ; risques techniques (≈1217).
   - Modèle : § 9 (contrôles de migration) ; § 10 (T1–T40) ; § 12.1.
   - `docs/architecture/README.md` : point **P8** (paliers commerciaux).
3. Pose les questions du § 2 avec `AskUserQuestion` avant de coder. Pour les services payants,
   **ne choisis rien à ma place**.
4. Plan → feu vert → exécution → vérification → clôture.

## 1. Objectif

Un backend déployé en préproduction, qui passe T1–T40 en CI, dont les déploiements sont bloqués
par la moindre fuite inter-tenant, observable, et capable d'importer un catalogue et des
clients au démarrage d'une entreprise.

## 2. Questions à me poser (AskUserQuestion)

1. **PostgreSQL managé** (doit offrir PostgreSQL 16, PITR, un pooler en **mode transaction**, et
   le rôle `coges_app` sans BYPASSRLS) : Neon / Supabase / autre (me demander lequel). Rappelle
   que psycopg 3 derrière un pooler en mode transaction exige de désactiver les requêtes préparées
   côté serveur (`prepare_threshold=None`).
2. **Redis managé** : Upstash / Redis Cloud / conteneur sur l'hôte des workers.
3. **Hôte des conteneurs Docker** (workers, beat, relais, ML) : Railway / Fly.io / VPS avec docker
   compose / autre.
4. **API sur Vercel** (Diagramme 2) : fonction Python Vercel avec `vercel.json` (Recommandé :
   conforme à l'architecture ; vérifie ensemble les limites de durée et de taille) / API dans un
   conteneur si les limites posent problème (écart à documenter).
5. **Import** : CSV **et** Excel (`.xlsx`) pour produits (avec prix et stock initial), catégories,
   clients et fournisseurs, avec validation complète **avant** écriture et rapport d'erreurs ligne
   par ligne (Recommandé) / CSV seulement. Import des ventes historiques : non en V1 (Recommandé) / oui.
6. **Limitation de débit** : par IP et par tenant, stockée dans Redis (Recommandé) / par IP
   seulement.
7. **Observabilité** : logs JSON + OpenTelemetry (traces) vers un fournisseur à choisir (me
   demander lequel) / Sentry pour les erreurs + logs JSON (Recommandé pour démarrer) / logs seuls.
8. **Paliers commerciaux (P8)** : aucune limitation par palier dans le code V1 (Recommandé : non
   prévu par l'architecture) / préparer une table de plan et des limites (écart à documenter).

## 3. Périmètre

**Import / export (`modules/importexport/`)**
- Téléversement → validation → aperçu des erreurs → confirmation → import dans **une**
  transaction par fichier (tout ou rien) ; le stock initial passe par des mouvements `initial`
  (façade Inventory) et les prix par `product_prices` (façade Products).
- Export CSV/Excel des référentiels et des ventes d'une période ; un export volumineux est une tâche
  worker (`exports.py`) dont le fichier est mis à disposition à la fin ; l'export est tracé en
  audit secondaire.

**Sécurité**
- Rate limiting (réponse 6) ; en-têtes de sécurité ; CORS limité au domaine du frontend ; taille
  maximale des requêtes et des fichiers ; revue des schémas Pydantic (`extra = forbid`, bornes) ;
  vérification que `Idempotency-Key` est exigé sur **toutes** les écritures financières.
- Revue des secrets : aucun dans le dépôt, rotation documentée de la clé JWT.
- **Cloisonnement du rôle `coges_owner`** : il est membre (`WITH INHERIT FALSE`) de `coges_auth` et
  de `coges_bus`, tous deux `BYPASSRLS` (ADR 0005, 0032). Il peut donc lire toutes les entreprises
  par un `SET ROLE`. Mets en place les trois garde-fous suivants, et teste-les :
  1. au démarrage de l'API **et** des workers, refus de démarrer si l'utilisateur du DSN
     applicatif est `coges_owner` ou possède `rolbypassrls` (vérification via `current_user` et
     `pg_roles`) ;
  2. en production, le DSN `coges_owner` n'existe **que** dans le job de migration de la CI :
     absent des variables d'environnement de Vercel et des conteneurs workers (vérifié par un
     script de contrôle dans la CI de déploiement) ;
  3. propose-moi (AskUserQuestion) de retirer l'appartenance `coges_owner → coges_auth/coges_bus`
     après chaque migration et de la rétablir seulement le temps d'une migration qui en a besoin,
     ou de la garder en la documentant dans `deploy/README-infra.md`.

**Déploiement**
- `vercel.json` et point d'entrée `backend/app/main.py` ; `Dockerfile.worker` ;
  `deploy/docker-compose.worker.yml` ; `deploy/README-infra.md` (base, cache, scheduler, rôles SQL,
  sauvegardes, **procédure de restauration testée**).
- Migrations exécutées comme **étape de déploiement** (job CI), jamais au démarrage.
- Environnements : `preview` (par branche) et `production`, avec des secrets distincts.

**CI bloquante**
- Jobs : lint, mypy, tests unitaires, tests d'intégrité **T1–T40**, tests de fuite
  (`tests/tenancy/`), tests d'architecture, `alembic upgrade head` → `downgrade -1` → `upgrade head`.
- Échec d'un test de fuite ⇒ déploiement impossible.
- Export de l'OpenAPI (`openapi.json`) versionné, et un test qui échoue si le contrat change sans
  mise à jour du fichier : c'est la source des types du frontend.

**Tests supplémentaires**
- Import : fichier avec erreurs ⇒ rien n'est écrit ; SKU en double ; import dans A invisible de B.
- Rate limiting : dépassement ⇒ 429.
- Test de fumée post-déploiement : health, login, lecture du tableau de bord.

## 4. Règles à respecter

- Le Diagramme 2 décide de la zone : tout ce qui est long, planifié ou persistant va dans Docker.
- Aucun service payant n'est provisionné sans mon accord explicite.

## 5. Vérification

Préproduction en ligne ; montre la CI verte (T1–T40 listés), le test de fumée, et un import de
20 produits avec une erreur volontaire corrigée.

## 6. Clôture

ADR (hébergeurs, pooler, observabilité, import) ; `CLAUDE.md` mis à jour, avec la phase 10 ✅ et
un encadré « **Backend V1 terminé** » qui liste les endpoints et l'URL de l'OpenAPI ; résumé.
