# Phase 13 — Frontend : finance, analytics, CoGes Intelligence, paramètres

---

Tu es l'agent de développement du projet **CoGes**. Nous démarrons la **phase 13 : les écrans de
pilotage**, pour le gérant et le comptable. Ils affichent des chiffres **déjà calculés par le
serveur** ; la règle clé : **toute métrique est nommée**, toute prévision est **datée et qualifiée**.

## 0. Protocole

1. Lis `CLAUDE.md` (phase 12 ✅ exigée) et les ADR (phases 07, 08, 09 et 11).
2. Lis `docs/design/prototype-reference.md` et les écrans 7 à 10 de
   `docs/design/prototype-bolt-prompt.md` ; dans l'architecture, les 8 métriques, le tableau
   CORRECT / INTERDIT et les règles d'affichage des prévisions (≈509-585).
3. Pose les questions du § 2 avec `AskUserQuestion` avant de coder.
4. Écran par écran, avec une capture et mon retour, sauf si je te dis d'enchaîner.
5. Clôture.

## 1. Objectif

Écrans Finance (vue d'ensemble, paiements, dettes, dépenses), Analytics (8 métriques),
CoGes Intelligence (insights et prévisions) et Paramètres (entreprise, utilisateurs, rôles,
journal d'activité), avec des parcours complets.

## 2. Questions à me poser (AskUserQuestion)

1. **Cartes d'Intelligence** : version compacte en grille (badge de type, titre, métrique, valeur,
   date, confiance) et détail complet dans un panneau latéral avec l'`evidence` en mini-graphique
   (Recommandé : corrige les cartes trop hautes du prototype) / cartes complètes comme le prototype.
2. **Sélecteur de métrique Analytics** : liste déroulante avec une courte définition de chaque
   métrique en infobulle (Recommandé) / onglets.
3. **Période** : sélecteur commun (7 j, 30 j, 90 j, mois en cours, personnalisé), mémorisé dans
   l'URL (Recommandé) / par écran.
4. **Enregistrer un règlement** depuis la liste des dettes : dialogue qui propose de répartir un
   paiement sur plusieurs dettes du même client (Recommandé : exploite les allocations) / une dette
   à la fois.
5. **Journal d'activité** : lecture paginée de l'audit (critique + secondaire) filtrable par
   utilisateur, action, entité et période, réservée au gérant (Recommandé) / autre règle d'accès.

## 3. Périmètre

- **Finance** : vue d'ensemble (encaissements / décaissements, CA net, coût des ventes, marge
  brute, dépenses, résultat estimé, série sur 30 jours), onglet Paiements, onglet Dettes (créances
  et dettes fournisseurs, échéances dépassées mises en évidence, règlement, abandon avec motif pour
  le gérant), onglet Dépenses (catégories, ajout, paiement).
- **Analytics** : sélecteur des 8 métriques, top 10 produits **pour la métrique choisie**, avec le
  nom de la métrique **visible sur chaque ligne** et sa définition ; séries CA et marge. Métrique 8
  sans forecast ⇒ message « données insuffisantes ».
- **CoGes Intelligence** : compteurs de synthèse (risques de rupture, prévisions, anomalies,
  données insuffisantes) ; liste des insights filtrable, changement de statut (lu, pris en compte,
  écarté, résolu) ; composant `components/forecast/` qui affiche **toujours** la date de calcul, le
  modèle et sa version, et l'incertitude ; si l'Intelligence est désactivée (`enabled: false`),
  l'écran l'explique et les blocs prédictifs du tableau de bord disparaissent proprement.
- **Paramètres** : Entreprise (nom, devise, fuseau, TVA activée, seuils par défaut, Intelligence
  activée) avec un avertissement avant toute modification sensible ; Utilisateurs (création,
  désactivation, rôle) ; Rôles et permissions (matrice en lecture, modification pour le gérant) ;
  Journal d'activité.
- **Notifications** : panneau depuis la cloche, marquage comme lu, lien vers l'élément concerné.

## 4. Règles à respecter

- Libellés **interdits** : « meilleur produit », « top produit » sans métrique, score combiné.
- Aucun « en direct » pour une prévision ; aucune valeur inventée ou nulle à la place de « données
  insuffisantes ».
- Aucun calcul financier côté client.
- L'`Idempotency-Key` est envoyé sur les paiements et les dépenses payées.

## 5. Vérification

Playwright : (1) paiement réparti sur deux dettes, puis soldes vérifiés ; (2) changement de
métrique Analytics, avec le libellé de la métrique vérifié ; (3) insight écarté ; (4) vendeur
qui n'accède pas aux Paramètres (masqué côté front **et** 403 côté API). Captures des écrans.

## 6. Clôture

`CLAUDE.md` mis à jour ; liste des écarts par rapport au prototype ; résumé. Le produit V1 est
fonctionnellement complet.
