# 0125 — Licence sur site : un abonnement actif sans fin, posé par une commande locale

- **Date** : 2026-11-17
- **Phase** : sur site, lot 2 (`docs/prompt-sur-site/02-licence.md`)
- **Statut** : acceptée
- **Décideur** : utilisateur (décisions écrites dans le prompt du lot 2)

## Contexte

Sur le PC d'un client (ADR 0124), toute entreprise naît avec l'essai Premium de 30 jours
(`companies_start_trial()`, révision 0028) et la tâche de nuit la suspend au 31ᵉ jour. En
ligne, l'équipe enregistre un paiement dans l'administration de la plateforme (ADR 0091) ;
sur site, l'administration n'existe pas (`/api/v1/platform/*` en 404), et ses fonctions
exigent un compte de l'équipe à double authentification (ADR 0105).

Constat dans le code : `run_subscription_day` ne regarde que les abonnements `trial`
(`trials_ending_before`). Un abonnement `active` n'est jamais suspendu automatiquement, et
`current_period_end` n'y change rien. **La licence existe donc déjà dans le comportement :
c'est un abonnement `active` sans fin.** Il manquait le moyen de la poser.

## Options envisagées

1. **Abonnement `active` sans fin, posé par une commande locale (retenue).** Aucune
   migration, aucune route, aucune tâche nouvelle ; la tâche de nuit, inchangée, ne le
   suit pas.
2. Clé de licence signée, vérifiée à chaque démarrage : une seule installation par client,
   un PC qui lui appartient ; la clé protégerait peu (le code et la base sont sur sa
   machine) et coûterait une infrastructure de signature, des pannes possibles au
   démarrage et un changement de la connexion. Écartée.
3. Une route ou l'administration de la plateforme livrée sur le poste : ouvrirait une
   surface réseau et un compte de l'équipe chez le client pour un geste fait une fois.
   Écartée.

## Décision

- `python -m app.cli activate-license --slug S --plan starter|business|premium [--note T]`
  appelle `platform_service.activate_license`, qui, **dans une transaction** sous
  `coges_app_platform` : trouve l'entreprise par son identifiant exact (recherche de
  l'administration, puis égalité stricte), verrouille entreprise puis abonnement (ordre de
  `_lock`), refuse une offre inconnue ou non commandable (`is_orderable`) et une offre plus
  petite que le nombre de comptes actifs (`PlanDowngradeTooManyUsersError`, comme
  l'administration), pose `plan_id`, `status = 'active'`, `current_period_end = NULL`,
  `updated_at`, rend l'accès (`ACCESS_OF['active']` par `_set_access`,
  `notify_manager=False`), et écrit l'audit critique de la plateforme avec
  `actor_id = NULL`, avant/après (offre, statut, fin de période), raison « licence sur
  site » et la note.
- `trial_ends_at` reste tel quel : la contrainte `subscriptions_trial_has_end` ne l'exige
  que pour un essai, et la date garde la trace de l'essai d'origine.
- **Idempotente** : même offre sur une licence déjà active (et accès déjà actif) ⇒ rien
  n'est écrit, aucune ligne d'audit, « Licence déjà active, offre X : rien à faire. ».
  Autre offre ⇒ l'offre change, auditée. Une période payée (`current_period_end` posé par
  un paiement) devient sans fin.
- **Réactivation** : une entreprise suspendue (essai fini) retrouve l'accès ; deux lignes
  d'audit (abonnement, accès), aucun message (aucun SMTP sur site).
- `python -m app.cli license-status --slug S` relit, sans rien écrire : nom, accès,
  statut, offre et plafond, comptes actifs, fin d'essai, fin de période (« sans fin »),
  dernière ligne d'audit de licence (date, note). Elle servira au support (lot 6) et la CI
  s'en sert.
- Sortie en français, codes de sortie : 0 fait ou rien à faire, 3 entreprise introuvable,
  4 offre inconnue ou non proposée (ou note de plus de 500 caractères), 5 offre trop petite.
- Ni compte de l'équipe ni double authentification : la commande n'est atteignable que
  depuis le conteneur `cli` du poste, qui tient déjà le DSN de `coges_app_platform` (lot 1).
  Qui peut lancer ce conteneur peut déjà lire et écrire la base ; une authentification de
  plus n'ajouterait aucune protection. C'est pourquoi `actor_id = NULL`, comme la tâche de
  nuit, que le journal accepte déjà : l'auteur est « le poste », et la note dit le contrat.

## La dérogation au garde-fou du lot 1

Le lot doit toucher deux fichiers protégés. `deploy/onprem/check_protected_paths.py` gagne
une table `DEROGATIONS` (chemin → raison, lot), **exactement** :

| Fichier | Raison | Lot |
|---|---|---|
| `backend/app/cli.py` | commandes `activate-license` et `license-status` | lot 2 |
| `backend/app/modules/platform/service.py` | fonctions `activate_license` et `license_status` | lot 2 |

Un fichier de la table n'est accepté que si `git diff --numstat BASE...HEAD` y montre
**0 ligne supprimée** (une ligne modifiée compte pour une suppression) ; un nombre
inconnu (binaire, ou `--paths` sans git) est refusé. Tout autre chemin protégé reste
refusé. `repository.py` n'a pas été touché : la recherche par identifiant passe par
`CompanyDirectory.search` puis l'égalité stricte, la dernière licence par `AuditReader`.

Pour rester en ajout pur, `cli.py` importe `datetime as dt` et `app.core.errors as
core_errors` sur des lignes nouvelles (fusionner avec les imports existants les aurait
modifiées).

**Limite connue** : le script est dans la PR ; une PR pourrait élargir sa propre table.
Parade : `test_the_derogation_table_is_exactly_the_one_of_lot_2` épingle la liste exacte,
et le propriétaire relit la table à la revue. Un lot suivant qui aurait besoin d'une
dérogation la remplace par la sienne, avec l'accord du propriétaire ; sinon il la vide.

## Budget mémoire : beat porté à 320 Mo (amende 0124)

Le job « Sur site » de la PR n° 93 a échoué au démarrage : `beat` redémarrait en code 137
dix secondes après son lancement, et `docker compose up --wait` l'a vu « unhealthy ». Le lot 2
ne change ni le compose ni ce que `beat` charge ; la cause existait déjà au lot 1 :

- au lot 1 (ADR 0124), `beat` était mesuré à 111 Mo au repos et 142 Mo pendant une vente ;
  sur les runs verts de `main` et de la PR n° 92, la CI le mesure déjà à **174 Mo** ;
- sur le poste, pendant `verifier.sh`, le groupe de contrôle de `beat` atteint son plafond
  (`memory.peak` = 224 Mo, compteur `max` à 348), sans être tué cette fois. Son bilan de santé
  lance un second Python (`python -m app.workers.health beat`) dans le même conteneur.
- mémoire anonyme seule (`memory.stat`, une prise par seconde, scénario complet) : **193 Mo**
  au repos, pics de **222 à 249 Mo** au démarrage et à chaque bilan de santé. Au-dessus de
  224 Mo, le noyau tue le processus : c'est le 137 de la CI.

Décision du propriétaire : plafond de `beat` à **320 Mo** (≈ 70 Mo de marge au-dessus du plus
haut pic vu ; 288 Mo passait le scénario mais n'en laissait que ≈ 39). Les plafonds des services
continus passent de 2 736 à **2 832 Mo**, toujours sous 3 Go (test inchangé). Le compose de production (`deploy/vps/`) n'est pas touché.

## Ce que la licence ne fait pas

- **Elle ne protège pas** contre un client qui modifierait la base : le PC lui appartient.
  La protection est contractuelle (contrat à venir).
- **Elle ne limite que le nombre de comptes actifs** (trigger `users_plan_limit`, `CG007`) :
  rien dans `backend/app/` hors `platform/` ne lit `plans.features`, les écrans sont les
  mêmes pour toutes les offres.
- Elle n'expire pas : la fin de maintenance est écrite dans la note, pas appliquée.

## Conséquences

- Aucune migration, aucune route (`openapi.json` identique), aucune tâche planifiée,
  aucune dépendance (`requirements.txt` identique).
- Interrupteur éteint : `test_onprem_license_is_cli_only.py` vérifie qu'aucun fichier de
  `app/` hors `cli.py` ne nomme les deux fonctions, et qu'aucune autre fonction de la
  façade ne les appelle. Sans la commande, le comportement est celui d'avant.
- Tests : `tests/integration/test_onprem_license.py` (licenciée jamais suspendue à +31,
  +90, +400 jours ; témoin suspendu à +31 ; plafond des trois offres en base ; montée et
  descente ; réactivation silencieuse ; idempotence ; refus ; isolation A/B ; empreinte de
  toutes les tables lisibles : seules `subscriptions`, `companies` (statut) et
  `platform_audit_logs` changent ; `license-status` en lecture seule ; sortie de la
  commande) ; dérogation dans `tests/unit/test_onprem_scripts.py`.
- `deploy/onprem-ci/verifier.sh` joue le premier démarrage complet : société, licence,
  `license-status` (« actif », « sans fin »), puis la tâche de nuit à +45 jours dans le
  conteneur worker : la société licenciée se connecte toujours, une société témoin sans
  licence est suspendue et sa connexion refusée (403 `company_suspended`).
- Guide : `docs/runbooks/sur-site.md`, étapes 8 à 11, « Premier démarrage : l'ordre à
  suivre », « Changer d'offre », « Ce qui se passe si on oublie la licence ».
- Pour que le PC de test trouve la commande, il faut des images qui la contiennent :
  une étiquette `vX.Y.Z` après la fusion, à décider avec le propriétaire.
