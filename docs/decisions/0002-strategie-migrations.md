# 0002 — Stratégie de migrations, types ENUM et base de test

- **Date** : 2026-09-23
- **Phase** : 01
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

Le § 9 du Modèle de données décrit une migration **V1 → V1.1**, alors que le projet part de
zéro (point ouvert **P1** de `docs/architecture/README.md`). Il fallait aussi décider quand
créer les 13 types ENUM du § 8.1 et sur quelle base exécuter les tests d'intégrité T1–T40.

## Options envisagées

1. **Schéma V1.1 direct, une révision Alembic par phase (retenue)** : `0001_platform`, puis
   `0002_referentiels`, `0003_stock`… Chaque phase livre un `upgrade` et un `downgrade` testés,
   de taille relisible ; la CI rejoue tout l'historique à chaque exécution.
2. Une seule révision créant tout le schéma V1.1 : cohérence immédiate, mais 1 200 lignes de SQL
   non exercées avant les phases 04 à 09 et un `downgrade` qui ne prouve rien.
3. Suivre littéralement V1 puis V1.1 : écrire puis corriger des tables sur un projet neuf.

## Décision

- **Une révision Alembic par phase**, créant directement le schéma V1.1.
- **Les 13 types ENUM sont créés dès `0001`**, copiés du § 8.1 : une seule source, aucun risque
  d'écart de valeurs entre phases, et un `downgrade` qui les supprime tous.
- **Base de test dédiée `coges_test`**, recréée en début de session pytest par
  `alembic downgrade base` puis `upgrade head` : les tests portent sur les **vraies** migrations,
  donc sur leurs triggers et leurs politiques RLS. Les tests se connectent en `coges_app`.
- L'autogénération Alembic est **désactivée** (`target_metadata = None`) : les migrations sont
  écrites à la main en SQL, fidèles au § 8. Une autogénération comparerait un schéma ORM partiel
  et proposerait des suppressions de tables.
- `migrations/env.py` n'écrase pas une `sqlalchemy.url` déjà posée par l'appelant, pour que la
  suite pytest migre `coges_test` sans jamais toucher la base de développement.

## Conséquences

- Chaque phase doit fournir un `downgrade` réellement testé : la CI enchaîne
  `upgrade head → downgrade base → upgrade head`.
- Les types ENUM des phases 04 à 09 existent déjà : `ALTER TYPE … ADD VALUE` reste visible d'un
  seul coup d'œil dans `0001` si une valeur devait être ajoutée.
- La suite de tests coûte une recréation complète du schéma par session, aujourd'hui de l'ordre
  de la seconde.
