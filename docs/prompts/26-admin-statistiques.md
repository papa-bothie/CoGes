# Prompt 26 — Lot admin 5 : statistiques

Branche `feat/admin-stats`, depuis `main` à jour, après les lots admin 1 et 3 (prompts 22 et 24) — a besoin du statut des entreprises et du modèle d'abonnement pour avoir des chiffres à afficher.

```
Lot admin 5 — Statistiques (branche feat/admin-stats, depuis main à jour, après les prompts 22
et 24). Règles habituelles : ADR aux prochains numéros libres, tests d'abord, ne jamais ouvrir
ni commiter .env, deploy/.env.preprod ni backend/.vercel/. Résumé en français à la fin,
questions ouvertes par AskUserQuestion.

Le plus simple des cinq lots : tout ce qu'il affiche existe déjà dans les tables posées par les
lots précédents. Aucune nouvelle table dans ce lot.

1. Indicateurs
   - GET /api/v1/platform/stats/overview : nombre d'entreprises par statut (trial/active/
     suspended), nombre total d'utilisateurs actifs (tous comptes commerçants confondus,
     is_active=true), répartition par plan (section 1 du prompt 24).
   - Revenu : somme de subscription_payments sur une période choisie (mois en cours, mois
     précédent, personnalisée), PAS un revenu récurrent théorique calculé depuis les plans
     actifs — seulement l'argent réellement déclaré reçu, pour ne jamais afficher un chiffre
     optimiste qui ne correspond à rien d'encaissé. Documente cette distinction dans l'écran
     lui-même (un sous-titre « basé sur les paiements enregistrés »), pas seulement dans l'ADR.
   - Nouvelles entreprises par semaine/mois sur les 12 derniers mois (pour voir une tendance,
     pas seulement un instantané).

2. Interface web (frontend-admin/)
   - Écran « Statistiques » : les indicateurs ci-dessus, filtrables par période. Pas de
     tableau de bord temps réel sophistiqué pour ce lot — des chiffres justes et clairement
     datés valent mieux qu'un graphique impressionnant mais ambigu.

3. Tests
   - Isolation déjà couverte par le rôle plateforme (vérifie juste que ces nouvelles routes sont
     classées dans le registre).
   - Le chiffre de revenu ne bouge QUE quand un paiement est enregistré (prompt 24), jamais
     quand un plan change ou qu'un essai commence.
   - Cohérence : la somme des entreprises par statut égale le nombre total d'entreprises à tout
     instant (test d'invariant, sur le modèle de tests/helpers/invariants.py du lot C).

Fin du lot : suite backend complète, make front-check, e2e de l'écran. Met à jour CLAUDE.md : à
ce stade, l'interface d'administration couvre les cinq points demandés initialement (entreprises,
abonnements, système, support, statistiques).
```
