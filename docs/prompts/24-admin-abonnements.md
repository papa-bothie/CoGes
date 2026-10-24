# Prompt 24 — Lot admin 3 : abonnements, offres et statuts de paiement

Branche `feat/admin-subscriptions`, depuis `main` à jour, après le lot admin 1 (prompt 22). Construit ce que la décision 0043 (point P8) avait explicitement laissé hors V1 : un modèle de plans et d'abonnements, avec trois offres à 4 900, 9 900 et 14 900 FCFA par mois (jusqu'à 3, jusqu'à 7, jusqu'à 10 utilisateurs), une période d'essai, et la possibilité d'ajouter plus tard un palier « sur devis » au-delà de 10 utilisateurs sans redévelopper le modèle.

```
Lot admin 3 — Abonnements (branche feat/admin-subscriptions, depuis main à jour, après le
prompt 22). Règles habituelles : ADR aux prochains numéros libres, tests d'abord, aucun service
payant, ne jamais ouvrir ni commiter .env, deploy/.env.preprod ni backend/.vercel/. Résumé en
français à la fin, questions ouvertes par AskUserQuestion.

Contexte décidé par le propriétaire : trois offres pour commencer — 4 900 FCFA/mois (jusqu'à 3
utilisateurs, fonctionnalités de base), 9 900 FCFA/mois (jusqu'à 7 utilisateurs, fonctionnalités
supplémentaires), 14 900 FCFA/mois (jusqu'à 10 utilisateurs, fonctionnalités premium — ces
fonctionnalités restent à construire, le palier existe dans le modèle avant d'exister dans le
produit). Plafond de 10 utilisateurs pour l'instant, SANS fermer la porte à un palier « sur
devis » au-delà de 10, à ajouter plus tard sans migration lourde.

1. Modèle de données (migration au prochain numéro libre)
   - Table plans (plateforme, hors RLS tenant) : id, code (starter, business, premium — noms
     internes stables, jamais affichés tels quels au commerçant), name (le nom commercial,
     modifiable sans toucher au code), price_fcfa (numeric, jamais float — même règle que le
     reste du projet), max_users (nullable : NULL = illimité, pour permettre un futur palier
     « sur devis » sans changer le schéma), features (jsonb ou table séparée plan_features —
     [DEMANDER] laquelle : jsonb est plus rapide à livrer mais moins interrogeable ;
     recommandation : jsonb pour ce lot, migration vers une table si la liste de fonctionnalités
     devient un argument de vente détaillé côté interface), is_orderable (bool — un palier
     « sur devis » qu'on prépare mais ne vend pas encore passe à false), created_at.
   - Seed des trois plans au prix et aux plafonds ci-dessus, is_orderable=true pour les trois ;
     prévois la ligne du futur palier « sur devis » dans l'ADR (pas dans le seed) :
     max_users=NULL, is_orderable=false, à activer le jour venu par une simple mise à jour, pas
     par un nouveau développement.
   - Table subscriptions (plateforme) : id, company_id (référence companies, mais CETTE table
     reste hors RLS tenant comme job_runs — c'est une donnée plateforme à propos d'une
     entreprise, pas une donnée DE l'entreprise), plan_id, status (enum : trial, active,
     past_due, suspended), trial_ends_at (nullable), started_at, current_period_end
     (nullable tant que le paiement est déclaratif). Une entreprise = un abonnement actif à la
     fois (contrainte d'unicité sur company_id parmi les lignes non terminées) — pas d'historique
     d'abonnements à gérer dans ce lot, juste l'état courant ; si l'historique devient utile,
     ajoute started_at/ended_at plus tard.
   - Table subscription_payments (plateforme) : id, subscription_id, amount_fcfa, paid_at,
     method (wave, orange_money, especes, virement — même liste que pay_method du reste du
     projet pour rester cohérent), note, recorded_by (platform_users.id). Déclaratif : une
     personne de l'équipe CipherOne saisit qu'un paiement a été reçu, aucune intégration de
     paiement automatique dans ce lot.

2. Durée et contenu de l'essai
   - [DEMANDER] : durée de la période d'essai (14 jours ? 30 jours ?) et ce qui se passe à son
     expiration sans paiement enregistré — suspension automatique (status -> suspended, même
     mécanisme que la suspension manuelle du prompt 22) ou dégradation vers un accès lecture
     seule. Recommandation : suspension automatique après l'essai, c'est le comportement déjà
     prévu pour companies.status=suspended depuis le prompt 22, rien de nouveau à construire
     côté accès.
   - Tâche planifiée (beat.py, registre du lot C à tenir à jour) : repère chaque nuit les
     abonnements trial dont trial_ends_at est dépassé et sans paiement, applique la décision
     ci-dessus, journalise dans job_runs, notifie l'équipe (pas le commerçant automatiquement à
     ce stade — à discuter si souhaité).

3. Faire respecter le plafond d'utilisateurs
   - La création d'un utilisateur (POST /users existant) doit maintenant vérifier le plafond
     max_users du plan actif de l'entreprise AVANT d'écrire. Au-delà : refus 409 avec un code
     dédié (plan_user_limit_reached) et un message clair orienté action (« Ce plan autorise
     {max_users} utilisateurs maximum. Passez à un palier supérieur pour en ajouter. »), jamais une erreur
     technique. Un plan dont max_users est NULL (le futur « sur devis ») n'a pas de plafond.
   - Test : au plafond exact -> refusé ; un de moins -> accepté ; plan NULL -> toujours accepté ;
     désactiver un utilisateur puis en créer un autre repasse sous le plafond (compte les
     utilisateurs actifs, pas le total historique).

4. Lecture et gestion côté plateforme
   - GET /api/v1/platform/plans, GET /api/v1/platform/companies/{id}/subscription : plan actif,
     statut, dates, historique des paiements déclarés.
   - PATCH /api/v1/platform/companies/{id}/subscription : changer de plan (upgrade ou downgrade
     — un downgrade qui ferait repasser sous le nombre d'utilisateurs actifs actuel est refusé
     avec un message qui dit combien désactiver d'abord, pas une erreur SQL), changer le statut.
     Audit critique (platform_audit_logs du prompt 22).
   - POST /api/v1/platform/companies/{id}/payments : enregistrer un paiement déclaré. Audit
     critique (c'est une donnée financière, même règle que le reste du projet pour l'argent).

5. Interface web (frontend-admin/)
   - Dans l'écran détail d'une entreprise (prompt 22) : carte abonnement (plan, statut, essai
     jusqu'au, dernier paiement), bouton changer de plan (liste déroulante des plans
     is_orderable=true seulement), bouton enregistrer un paiement (formulaire simple : montant,
     date, moyen, note).
   - L'écran « Statistiques » n'est PAS dans ce lot (prompt 26) ; ici, juste de quoi gérer un
     abonnement entreprise par entreprise.

6. Tests
   - Isolation : subscriptions et subscription_payments sont des tables plateforme, aucun accès
     depuis un jeton commerçant à aucune route ; classées dans le registre de rôle du prompt 22
     (le rôle coges_app_platform, s'il a été retenu, a bien le GRANT sur ces deux nouvelles
     tables).
   - Expiration d'essai : tâche testée à J-1 (rien ne se passe), J+0 exact (suspend), relance
     manuelle idempotente (ne suspend pas deux fois, ne double pas la notification).
   - Plafond d'utilisateurs : scénarios de la section 3, plus un downgrade refusé comme décrit.

Fin du lot : suite backend complète, ruff, mypy, make front-check, e2e des écrans concernés.
Met à jour CLAUDE.md (le modèle plans/subscriptions existe désormais, ADR qui referme
explicitement le point P8 en citant la décision 0043 qu'il remplace) et README-infra.md si une
nouvelle variable d'environnement est nécessaire pour la durée d'essai.
```

## Ce que le propriétaire fait lui-même

1. Répondre aux questions `AskUserQuestion` (durée d'essai, comportement à l'expiration, jsonb vs table pour les fonctionnalités) avant que l'agent commence à coder.
2. Confirmer les noms commerciaux des trois offres (Starter/Business/Premium ou autres) s'ils doivent apparaître tels quels dans l'interface.
