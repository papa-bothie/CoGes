# 0065 — Heure figée et seed de la maquette

- **Date** : 2026-10-07
- **Phase** : 15 (lot F)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion, 2026-10-07) ; prompt de phase 15 (règles 4 et 5)

## Contexte
Pour comparer le front aux captures de la maquette au pixel près, il faut les mêmes données
(« Alimentation Keur Fatou », mardi 6 octobre 2026 à 10 h 45) et le même « aujourd'hui ». Or
les données de la maquette se contredisent d'un écran à l'autre, et même dans l'accueil : les
cinq dernières ventes font 90 000 F quand la tuile annonce 87 500 F pour 14 ventes ; la liste
des ventes en montre 4 aujourd'hui (« 88 200 F ») ; la vente de 8 h 47 est payée sur l'accueil
et annulée dans la liste ; les dettes de Moussa Fall diffèrent entre sa fiche et
« Encaisser une dette ».

## Options envisagées
Pour le seed :
1. **Un seed cohérent, au plus près (retenue)** : boutique, personnes, articles, clients,
   fournisseurs, tuiles et graphique de l'accueil exacts, le reste ajusté pour que tout se
   tienne ; chaque chiffre qui diffère est listé dans `ecarts.md`.
2. Corriger d'abord la maquette.
3. Un jeu de données par écran, recréé avant chaque capture.

Pour l'heure : figer toute l'horloge (base comprise) ou seulement les **lectures** métier.

## Décision
- **`COGES_FROZEN_NOW`** (date avec fuseau) : `app/core/clock.py` le renvoie comme
  « maintenant » pour les **lectures** métier (tableau de bord, périodes, retards des dettes,
  fraîcheur des recommandations). Accepté seulement si `COGES_ENV` vaut `local` ou `ci` :
  refusé au démarrage en `staging` comme en `production` (correction du 07/10). Gardent
  l'heure réelle : jetons, sessions, limites de débit, idempotence, expirations, horodatages
  écrits par la base, et les gardes d'antidatage (ADR 0015), qui refuseraient sinon chaque
  mouvement après 48 h.
- **`make seed-maquette`** (`app/seed_maquette.py`) crée l'entreprise à part `maquette`
  (`coges` en local ; `coges_e2e` à chaque `make e2e-reset`), par les façades comme
  `seed-demo`. Le plan des 1 046 ventes est calculé avant toute écriture ; la dernière porte
  le n° 1046 comme dans la maquette. En fin de remplissage, `restamp` recale les dates que
  le serveur a posées lui-même (voir « Conséquences »). Exacts : 87 500 F et 14 ventes aujourd'hui, le graphique
  des 7 jours (568 500 F), les clients qui doivent 54 500 F (5 dettes reconstituées), les
  fournisseurs à qui l'on doit 185 000 F, les dépenses du mois (237 500 F), les stocks et
  seuils des articles, les personnes (Fatou Diop, Modou Sène, Awa Ndiaye au compte coupé).
- **API et front à part pour la comparaison** (:8101 à l'heure figée, cache Redis n° 2 ;
  :3101) : les autres parcours e2e gardent l'heure réelle. Côté navigateur, `page.clock`.
- **`make maquette-check`** (`e2e/maquette.spec.ts`, `playwright.maquette.config.ts`) :
  lit `ecrans.md`, capture à 1280 et 390 px, compare avec `pixelmatch`, écrit les images à
  trois panneaux et `comparaison.md`. Seuil 2 %, sauf écran listé dans `ecarts.md`. Écrans pas
  encore refaits en `test.fixme` avec leur lot ; `MAQUETTE_ALL=1` les mesure sans échouer.

## Conséquences
- **Dates du remplissage recalées** (correction du 07/10, levée de la limite de l'ADR 0060
  pour `maquette` seulement). Le serveur date lui-même encaissements de confirmation,
  sorties de stock, livraisons, dettes, `created_at` des clients et articles, audit, outbox,
  à l'heure du remplissage. `restamp(engine, company_id, moments)`, à la fin de
  `app/seed_maquette.py`, les ramène à l'heure de leur opération d'origine : la vente
  (encaissement, sortie de stock, dette, lignes, audit, événement), l'annulation (vente
  + 3 min : contre-écriture, retour en stock), la livraison du 3 octobre à 11 h, la dette de
  Sénégal Distribution le 18 septembre, le dernier règlement lettré (dette soldée), et le
  1er septembre à 6 h 30 pour ce qui précède la première vente (entreprise, comptes, rayons,
  articles, prix, clients, fournisseurs). Rien ne dépasse le 6 octobre 10 h 45.
  - Exécuté sous le **rôle propriétaire** (`COGES_DATABASE_URL_OWNER`), jamais par l'API ;
    une seule transaction, contexte tenant posé (la RLS FORCE s'applique au propriétaire),
    chaque requête filtrée sur `company_id`.
  - Les triggers utilisateur des tables touchées (journal append-only, `updated_at`,
    recalcul des soldes) sont coupés puis rétablis **dans** cette transaction : seules des
    dates changent, jamais un montant ni une quantité. `ALTER TABLE` y pose un verrou
    exclusif : à lancer sur une base locale ou e2e, pas sous charge.
  - `tests/integration/test_seed_maquette.py` sème l'entreprise entière (≈ 1 min 30 de plus
    dans `make test`) et vérifie qu'aucune colonne de date de ses tables ne dépasse
    `COGES_FROZEN_NOW` (échéances et expirations exceptées), que chaque encaissement, sortie
    de stock et dette d'une vente porte son heure, et que les triggers sont rétablis.
  - « Dans la caisse » et « Entrées et sorties de caisse » peuvent donc égaler la maquette
    au lot 3a/3d. Une entreprise réelle (`seed-demo`, ADR 0060) garde la limite.
- Les écarts de données sont listés dans `docs/design/maquette-v2/ecarts.md`.
