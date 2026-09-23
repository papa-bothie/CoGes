# Phase 14 — Finition visuelle avec la skill Impeccable

---

Tu es l'agent de développement du projet **CoGes**. Le produit V1 est fonctionnellement complet.
Nous démarrons la **phase 14 : finition visuelle** avec la skill **Impeccable**
(https://impeccable.style). L'objectif est de passer d'une interface « générée » à une interface
soignée, **sans toucher au comportement** : aucune règle, aucun appel API, aucun parcours ne change.

## 0. Protocole

1. Lis `CLAUDE.md` (phase 13 ✅ exigée), `docs/design/prototype-reference.md` (dont § 5, défauts
   connus) et les ADR front.
2. **Installation** : vérifie si Impeccable est déjà installé. Sinon, demande-moi l'autorisation,
   puis installe-le avec `npx impeccable install` (ou via `/plugin` → Discover → Impeccable). Ne
   lance aucune commande de la skill avant cette étape.
3. Pose les questions du § 2 avec `AskUserQuestion`.
4. Travaille **par passes**, dans l'ordre du § 3. Après chaque passe : captures avant / après,
   liste des fichiers modifiés, et **mon accord avant la passe suivante**.
5. Clôture.

## 1. Objectif

Une interface cohérente, lisible, dense sans être chargée, adaptée à un logiciel de gestion
financière utilisé toute la journée, et documentée dans un `DESIGN.md`.

## 2. Questions à me poser (AskUserQuestion)

1. **Direction visuelle** : garder l'identité du prototype (bleu pétrole, sobre, rassurant) et
   seulement la raffiner (Recommandé) / explorer une identité plus affirmée (proposer 2 pistes).
2. **Périmètre** : toutes les pages (Recommandé) / d'abord les 3 écrans de démo (nouvelle vente,
   stock, CoGes Intelligence).
3. **Animations** : micro-interactions discrètes seulement (retours de clic, transitions de
   panneaux), en respectant `prefers-reduced-motion` (Recommandé) / aucune / plus expressives.
4. **Densité des tableaux** : un réglage compact / confortable dans les préférences utilisateur
   (Recommandé : les comptables préfèrent le compact) / une seule densité.

## 3. Passes (commandes Impeccable)

1. `/impeccable init` puis `/impeccable document` : produire `docs/design/DESIGN.md` à partir des
   tokens existants (couleurs, rayons, ombres) **avant** toute modification.
2. `/impeccable audit` : rapport sur l'ensemble des pages (contraste, hiérarchie, espacement,
   « défauts d'IA » détectés). Présente-le-moi trié par gravité ; on choisit ensemble ce qu'on
   corrige.
3. `/impeccable typeset` : police définitive, échelle typographique, **chiffres tabulaires** pour
   tous les montants et quantités, montants jamais coupés sur deux lignes.
4. `/impeccable layout` : grilles du tableau de bord et des fiches, espacements, alignements,
   largeur de lecture ; comportement sur tablette.
5. `/impeccable colorize` : usage des couleurs d'état (succès, alerte, danger) réservé à leur sens ;
   badges de statut plus discrets que les boutons ; graphiques lisibles en clair et en sombre ;
   contraste AA vérifié.
6. `/impeccable clarify` puis `/impeccable distill` : libellés, états vides, messages d'erreur ;
   retirer le superflu (cartes d'Intelligence en particulier).
7. `/impeccable animate` et `/impeccable delight` : seulement selon la réponse 3.
8. `/impeccable polish` : passe finale, puis nouvel `/impeccable audit` pour comparer avec la passe 2.

Les noms de commandes peuvent évoluer : vérifie la liste réelle après l'installation et
signale-moi toute différence.

## 4. Règles à respecter

- **Aucun changement fonctionnel** : les tests Playwright des phases 11 à 13 doivent rester verts
  après **chaque** passe.
- Les règles d'affichage métier sont intouchables : métrique nommée, date de calcul, modèle et
  version, incertitude, « données insuffisantes », montants en FCFA sans décimales.
- Les modifications passent par les tokens et les composants partagés, pas par des styles isolés
  page par page.
- Accessibilité AA maintenue ou améliorée (vérifiée par un outil comme axe).

## 5. Vérification

Rapport final : audit avant / après, captures des écrans principaux en clair et en sombre, tests
e2e verts, score d'accessibilité.

## 6. Clôture

`docs/design/DESIGN.md` à jour ; `CLAUDE.md` avec la phase 14 ✅ ; résumé et liste des
améliorations reportées.
