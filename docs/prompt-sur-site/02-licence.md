# Sur site, lot 2 — La licence : `activate-license` et le premier démarrage

> **STATUT : PRÊT À LANCER** (17 novembre 2026). Deuxième des six lots de l'installation sur site. **Prérequis : le lot 1 (PR `feat/sur-site-assemblage`) est fusionné dans `main`.** Sinon l'agent s'arrête et le dit.

Branche `feat/sur-site-licence`, depuis `main` à jour. Une seule PR.

## Le plan d'ensemble (rappel)

| Lot | Contenu | État |
|---|---|---|
| 1 | Assemblage : CoGes démarre sur `http://localhost` | ✅ code et CI, à vérifier sur Windows |
| **2 (ce prompt)** | Commande `activate-license`, lecture de l'état, premier démarrage | ⬜ |
| 3 | Script d'installation Windows | ⬜ |
| 4 | Sauvegarde et restauration locales | ⬜ |
| 5 | Mises à jour à distance et retour arrière | ⬜ |
| 6 | Support à distance et journaux | ⬜ |

## Ce que j'ai vérifié dans le code avant d'écrire ce prompt

- `companies_start_trial()` (révision 0028) donne à **toute** entreprise un essai Premium de 30 jours. Ce déclencheur ne se modifie pas : une migration s'appliquerait aussi à la production.
- La tâche de nuit `run_subscription_day` ne regarde que les abonnements au statut `trial` (`trials_ending_before`). Un abonnement `active` n'est **jamais** suspendu automatiquement, et `current_period_end` n'y change rien. **La licence existe donc déjà dans le comportement du code : c'est un abonnement `active` sans fin.** Il manque seulement le moyen de le poser sans l'administration de la plateforme, absente chez le client.
- Les fonctions de `modules/platform/service.py` (`change_subscription`, `record_payment`) exigent un `PlatformAdmin`, c'est-à-dire un compte de l'équipe avec double authentification. La tâche de nuit, elle, écrit son audit avec `actor_id=None` : le journal l'accepte.
- Rien dans `backend/app/` hors `platform/` ne lit `plans.features` : seul le plafond d'utilisateurs (`max_users`, trigger `users_plan_limit`, `CG007`) est appliqué. Le plan choisi fixe donc surtout le nombre de comptes.
- Le service `cli` du compose sur site reçoit déjà `COGES_DATABASE_URL_PLATFORM` (rôle `coges_app_platform`) : la commande n'a besoin d'aucun nouveau secret.
- Le front commerçant n'affiche aucune page d'abonnement ; l'administration n'est pas livrée chez le client. Un abonnement `active` sans date de fin n'a donc aucun écran à casser.

## Décisions déjà prises

- **Licence = abonnement `active` sans date de fin**, posé par une commande locale. Pas de clé signée (une seule installation ; la protection est contractuelle, voir le contrat à venir).
- **Changement de plan** (vente additionnelle) : on relance la commande avec un autre plan. Passage à un plan plus petit refusé s'il y a plus de comptes actifs que le plafond, comme dans l'administration.
- **Commande, pas route.** Aucun endpoint nouveau : `openapi.json` ne bouge pas. Aucune tâche planifiée nouvelle.
- **Une entreprise suspendue peut être réactivée** par la commande (client qui paie après la fin de l'essai). Le gérant n'est pas notifié par e-mail (aucun SMTP sur site).
- **Le premier démarrage** devient une procédure unique, écrite dans le guide et rejouée par la CI : réglages → contrôle → migrations → démarrage → société → licence → connexion. Le script Windows qui l'automatisera est le lot 3.

## Dérogation au garde-fou du lot 1

Ce lot **doit** modifier du code de l'application (`backend/app/cli.py`, `backend/app/modules/platform/service.py`). Le contrôle des chemins protégés le refuserait. On ne le contourne pas : on lui apprend une dérogation **étroite, nommée et en ajout seulement**.

- `deploy/onprem/check_protected_paths.py` gagne une table `DEROGATIONS` : chemin → raison → lot. Pour ce lot, exactement : `backend/app/cli.py` et `backend/app/modules/platform/service.py` (et `backend/app/modules/platform/repository.py` seulement si la recherche par identifiant de connexion l'exige).
- Un fichier de la table n'est toléré que si le diff de la PR contre sa base **ne supprime aucune ligne** (`git diff --numstat` : colonne des suppressions à 0). Une ligne modifiée ou retirée ⇒ REFUS, même dans un fichier dérogé.
- Tout autre chemin protégé reste refusé, comme avant.
- Limite connue, à écrire dans l'ADR : le script étant dans la PR, une PR pourrait élargir sa propre table. Parade : un test épingle la table à la liste exacte ci-dessus, et le propriétaire relit la table à la revue.

## Prompt à donner à l'agent

```
Lot « Sur site 2 : licence » (branche feat/sur-site-licence, depuis main à jour). Règles
habituelles : ADR au prochain numéro libre (0125 attendu), tests d'abord (rouge puis vert,
cette fois pour de vrai : écris chaque test et vois-le échouer avant le code), aucun service
payant, ne jamais ouvrir ni commiter .env, deploy/.env.preprod, backend/.vercel/ ni
/etc/coges/*. Résumé en français à la fin, questions ouvertes par AskUserQuestion.
Si le lot 1 (ADR 0124, deploy/onprem/) n'est pas dans main, ARRÊTE-TOI et dis-le moi.

But : poser une licence sur site SANS l'administration de la plateforme, par une commande
locale ; documenter et rejouer en CI le premier démarrage complet.

Lis d'abord : docs/prompt-sur-site/02-licence.md (ce lot) et README.md, docs/decisions/0124-*,
docs/runbooks/sur-site.md, deploy/onprem/ (compose, check_protected_paths.py, ses tests dans
backend/tests/unit/test_onprem_*.py), deploy/onprem-ci/verifier.sh, backend/app/cli.py,
backend/app/modules/platform/service.py (section « abonnements », ADR 0091 : ACCESS_OF,
_lock, _set_access, _audit, change_subscription, record_payment, run_subscription_day),
backend/app/modules/platform/repository.py (SubscriptionRepository, CompanyDirectory),
backend/app/workers/tasks/platform.py (subscriptions_daily), la révision 0028,
backend/tests/integration/test_subscriptions_api.py et platform_harness.py,
docs/decisions/0091, 0089.

Principes non négociables
- AJOUTER, NE RIEN SUPPRIMER NI MODIFIER dans le code existant. Les seuls fichiers protégés
  que tu touches : backend/app/cli.py et backend/app/modules/platform/service.py (plus
  repository.py si strictement nécessaire, et dis pourquoi), uniquement par AJOUT de lignes.
  Aucune ligne existante n'est modifiée ou retirée : un `git diff` de ces fichiers ne montre
  que des « + ». Si tu penses devoir toucher autre chose (une migration, une route, un
  modèle, le trigger d'essai, la tâche de nuit, le front, deploy/vps, deploy.yml), ARRÊTE-TOI
  et demande-le-moi avec la raison.
- Aucune migration, aucune route, aucune tâche planifiée, aucune dépendance nouvelle.
  `backend/openapi.json` et `backend/requirements.txt` restent identiques (make
  check-generated).
- Interrupteur éteint par défaut : la nouvelle fonction n'est appelée que par la commande
  CLI. Un test d'architecture vérifie qu'aucun router, aucune tâche de worker et aucun autre
  module ne l'importe ni ne l'appelle. Sans la commande, le comportement est identique à
  aujourd'hui.
- Le secret ou le mot de passe ne passe jamais en argument de commande.

BLOC A — La commande `activate-license`
- `python -m app.cli activate-license --slug <identifiant de connexion> --plan
  starter|business|premium [--note "texte libre"]`. Choisis les codes de plan depuis la table
  `plans` (refus clair d'un code inconnu ou non commandable, `is_orderable`).
- Une fonction dans `modules/platform/service.py` (ajoutée à la fin de la section
  abonnements), sous `platform_transaction()`, qui, dans UNE transaction :
  1. trouve l'entreprise par son slug (lecture des seules colonnes déjà permises au rôle
     `coges_app_platform` ; sinon par `CompanyDirectory`) et verrouille entreprise puis
     abonnement dans l'ordre de `_lock` ;
  2. refuse un plan plus petit que le nombre de comptes actifs (même erreur
     `PlanDowngradeTooManyUsersError` que l'administration) ;
  3. pose `plan_id`, `status = 'active'`, `trial_ends_at` inchangé ou nul selon ce que permet
     la contrainte `subscriptions_trial_has_end`, `current_period_end = NULL` (« sans fin »),
     `updated_at` ;
  4. met `companies.status` à l'accès de `ACCESS_OF['active']` par `_set_access` avec
     `notify_manager=False` (aucun message) et la raison « licence sur site » ;
  5. écrit l'audit critique de la plateforme avec `actor_id=None`, avant/après (plan, statut,
     fin de période) et la note ; jamais de secret.
- Idempotente : relancée avec le même plan sur une licence déjà active, elle ne change rien et
  le dit (« déjà active, plan X, rien à faire ») sans nouvelle ligne d'audit. Avec un autre
  plan : le plan change, c'est audité.
- Sortie en français, stable, lisible par un débutant : entreprise, plan, plafond de
  comptes, statut avant → après. Code de sortie non nul et message clair pour : entreprise
  introuvable, plan inconnu, descente refusée.
- Aucune exigence de double authentification ni de compte de l'équipe : la commande n'est
  atteignable que depuis le conteneur `cli` du poste, où l'on tient déjà le DSN de la
  plateforme. Écris-le dans l'ADR comme décision assumée, avec le raisonnement.

BLOC B — La commande `license-status` (lecture seule)
- `python -m app.cli license-status --slug <slug>` affiche : nom, statut d'accès, plan,
  plafond de comptes, comptes actifs, fin d'essai, fin de période (« sans fin »), dernière
  ligne d'audit de licence (date, note). Aucune écriture. Elle servira au support (lot 6) et
  à la CI.
- Même transaction de lecture sous le rôle plateforme.

BLOC C — Garde-fou : la dérogation (deploy/onprem/check_protected_paths.py)
- Ajoute la table DEROGATIONS décrite dans docs/prompt-sur-site/02-licence.md : exactement
  backend/app/cli.py et backend/app/modules/platform/service.py (repository.py seulement si tu
  y es contraint), chacun avec sa raison et « lot 2 ». Un chemin de la table n'est accepté
  que si `git diff --numstat BASE...HEAD` y montre 0 ligne supprimée ; sinon REFUS qui nomme
  le fichier et le nombre de lignes supprimées. Tout autre chemin protégé reste refusé.
- Tests (dans les tests onprem existants, sans affaiblir les anciens) : un chemin protégé
  hors table est refusé ; cli.py avec des ajouts seulement passe ; cli.py avec une ligne
  supprimée ou modifiée est refusé ; la table est égale à la liste exacte du lot (test qui
  échoue si on l'élargit).
- Le workflow `onprem.yml` et l'ADR 0124 sont mis à jour (ajout, pas réécriture) pour décrire
  la dérogation.

BLOC D — Tests de la licence (backend/tests/…, rouge d'abord)
- Preuve centrale : une entreprise créée (essai de 30 jours), licence activée, puis la tâche
  de nuit (`run_subscription_day` avec `now` à +31 jours, +90 jours, +400 jours) NE LA SUSPEND
  PAS, n'envoie aucun avertissement d'essai, et `companies.status` reste `active`. Le même
  scénario SANS licence suspend à +31 jours (contrôle témoin : le test échoue bien quand on
  retire l'activation).
- Les trois plans : plafond de comptes appliqué par le trigger (le (max+1)ᵉ compte actif est
  refusé, `CG007`), changement starter → business relève le plafond, business → starter
  refusé avec N comptes de trop et accepté une fois ramené sous le plafond.
- Entreprise suspendue (essai fini) puis licence : accès rendu, aucune notification mise en
  file, audit des deux changements (abonnement et accès).
- Idempotence (deux appels : une seule ligne d'audit), entreprise introuvable, plan inconnu,
  plan non commandable.
- Isolation : activer la licence de A ne touche pas l'abonnement ni l'accès de B (B reste en
  essai, la tâche de nuit le suit toujours).
- La commande n'écrit rien en dehors de `subscriptions`, `companies.status` et le journal de
  la plateforme (compare avant/après les tables du schéma : aucun autre changement).
- `license-status` : lecture seule (aucune ligne écrite), bons champs dans chaque état.
- Architecture : la fonction d'activation n'est importée que par app/cli.py ; aucun router ni
  worker ne l'appelle ; le diff de cli.py et service.py ne contient que des ajouts.
- Non-régression : test_subscriptions_api.py, test_platform_*.py et tous les tests existants
  passent SANS aucune modification ; le job `vps` et check_runtime_env.py restent verts sans
  modification ; `make check-generated` est vide.

BLOC E — Premier démarrage, de bout en bout
- docs/runbooks/sur-site.md gagne la section « Premier démarrage » (PowerShell, pour un
  débutant), dans l'ordre : réglages remplis → contrôle des réglages → migrations →
  démarrage → création de la société (`docker compose … run --rm cli create-company …`, mot
  de passe demandé en interactif, jamais dans la ligne de commande, avec la précaution du
  terminal interactif `-it` sous Windows) → licence (`activate-license`, avec le plan acheté
  et une note contenant la date du contrat et celle de fin de maintenance) → vérification
  (`license-status`) → ouverture de http://localhost, connexion du gérant. Ajoute « Changer
  de plan » (relancer la commande) et « Ce qui se passe si on oublie la licence » (au
  31ᵉ jour l'accès est suspendu ; la commande le rend).
- deploy/onprem-ci/verifier.sh joue ces étapes, y compris : `activate-license`, puis
  `license-status` attendu « actif, sans fin », puis la tâche de nuit des abonnements lancée
  avec un `now` à +45 jours dans le conteneur worker (qui a le DSN plateforme), puis la
  connexion du gérant TOUJOURS acceptée ; et le contrôle témoin sur une seconde entreprise
  sans licence, suspendue à +45 jours, dont la connexion est refusée. Garde la durée totale du
  job raisonnable.
- Le conteneur `cli` ne doit toujours pas recevoir le DSN propriétaire (test du lot 1
  inchangé et vert).

Documentation
- ADR 0125 : pourquoi « abonnement actif sans fin » plutôt qu'une clé signée ; pourquoi une
  commande locale plutôt qu'une route ou l'administration ; pourquoi `actor_id=None` ; la
  dérogation étroite au garde-fou et sa limite ; ce que la licence ne protège pas (le PC est
  au client : protection contractuelle) ; ce qu'elle ne fait pas (les fonctions du plan ne
  sont pas limitées, seul le nombre de comptes l'est) ; réactivation d'une entreprise
  suspendue.
- docs/prompt-sur-site/README.md : lot 2 coché, table des fichiers à jour. CLAUDE.md : une
  ligne dans la section 8 et dans le journal des décisions (ADR 0125), sans le faire grossir.

Tu ne peux pas tester sous Windows : termine le résumé par ce qui reste à vérifier sur la
machine Windows pour ce lot (créer la société et activer la licence depuis PowerShell, mot de
passe saisi dans le terminal interactif, `license-status`), et par le tableau « fichier
protégé touché : lignes ajoutées / supprimées (0 attendu) ».

Fin de lot : suite complète verte, jobs `vps` et « Sur site » verts, PR ouverte, NE FUSIONNE
PAS et ne pousse aucune étiquette de version.
```

## Ce que le propriétaire fait ensuite

1. **Vérifier la fusion du lot 1** avant de lancer ce lot (et que la CI « Sur site » y était verte).
2. **Lancer le prompt** avec Claude Code sur `feat/sur-site-licence`. Pendant la revue, lire la **table des dérogations** du script de contrôle : elle doit contenir exactement deux fichiers (trois avec une justification claire).
3. **Après la fusion : publier une version.** La commande vit dans le code de l'application, donc dans les images. Pour que le PC de test la trouve, il faut des images qui la contiennent : poser une étiquette `vX.Y.Z` fabrique les images (et déploie la préproduction, pas la production). Le prochain déploiement de production embarquera aussi la commande, sans effet tant que personne ne la lance. À décider avec moi avant d'étiqueter.
4. **Sur la machine Windows :** suivre la section « Premier démarrage » du guide : société, licence, `license-status`, connexion. Rapporter ce qui marche et les messages d'erreur exacts.
5. Rien d'autre à déployer en production pour ce lot.
