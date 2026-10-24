# Prompt 27 — Lot admin 4 : interface d'administration modernisée et gestion des accès de l'équipe

Branche `feat/admin-ux-access`, depuis `main` à jour, après les lots admin 1 à 3 (prompts 22 à 26 fusionnés). Reprend l'application `frontend-admin/` (ADR 0089 à 0093) : mêmes écrans, mêmes règles de sécurité, nouvelle interface au thème CoGes, et ce qui manque pour gérer les accès de l'équipe (invitations, profils, suspension, journal des modifications).

Pourquoi ce lot : l'administration actuelle fait le travail mais elle est austère (barre du haut, bleu neutre voulu « distinct » par l'ADR 0089, tableaux bruts), et deux gestes du quotidien n'ont pas d'écran : gérer l'équipe (aujourd'hui uniquement par `make create-platform-user`) et retrouver qui a fait quoi (le journal `platform_audit_logs` est écrit mais jamais lisible). Le principe qui guide tout le lot : **on conçoit d'abord les tâches de l'administrateur, ensuite seulement le décor**. Une belle interface qui ralentit la gestion des accès est un échec.

Décisions du propriétaire (AskUserQuestion, à ne pas rouvrir) :
- Comptes gérés dans l'interface : **l'équipe plateforme** (profils `administrator` et `support`). Les utilisateurs des commerçants sont **listés et filtrables en lecture seule** ; l'administration ne les modifie pas (l'ADR 0089 reste intact : aucun droit d'écriture nouveau sur les tables des commerçants).
- Invitations : **par e-mail, pour l'équipe seulement**.
- Permissions : **deux profils fixes, expliqués en clair** ; changer le profil d'un compte = changer ses permissions. Pas de cases à cocher par compte.
- Thème : **thème CoGes avec un repère « Administration » toujours visible** (amende le « volontairement distinct » de l'ADR 0089).

```
Lot admin 4 — Interface d'administration et gestion des accès (branche feat/admin-ux-access,
depuis main à jour). Règles habituelles : ADR aux prochains numéros libres, tests d'abord
(rouge puis vert), aucun service payant, ne jamais ouvrir ni commiter .env,
deploy/.env.preprod ni backend/.vercel/. Résumé en français à la fin, questions ouvertes par
AskUserQuestion. Lis d'abord frontend-admin/README.md, les ADR 0064, 0089 à 0093,
frontend/app/globals.css (jetons de la maquette v2) et docs/design/DESIGN.md.

Aucune règle de sécurité existante ne s'assouplit : le rôle PostgreSQL coges_app_platform
n'obtient AUCUN droit sur les tables des commerçants, les jetons plateforme et commerçant
restent à audiences distinctes, chaque écriture reste auditée dans platform_audit_logs et
relue en base à chaque requête (CurrentPlatformAdmin). Si une exigence ci-dessous semble
l'exiger, arrête-toi et demande-moi.

D0. Préalable
- Captures « avant » de chaque écran existant (connexion, entreprises, fiche, statistiques,
  système, tâches) en clair et en sombre, dans docs/design/captures/admin/avant/.
- Chronomètre de référence : note, pour chaque tâche de D1, le nombre de clics et d'écrans
  AUJOURD'HUI. Ce sont les chiffres à battre.

D1. Les tâches de l'administrateur, d'abord (elles fixent l'écran, pas l'inverse)
Chacune devient un parcours e2e avec un nombre de clics MAXIMUM, vérifié en test :
 1. Retrouver un compte ou une entreprise : depuis n'importe quelle page, en 2 actions
    (focus de la recherche au raccourci « / », saisie, ouverture du résultat).
 2. Suspendre ou réactiver une entreprise ou un compte de l'équipe : 3 clics + confirmation.
 3. Inviter un collègue : 4 champs au plus (nom, e-mail, profil), 1 bouton.
 4. Changer le profil d'un collègue : 3 clics + confirmation.
 5. Savoir qui a fait quoi sur un compte ou une entreprise : 2 clics depuis la fiche.
 6. Voir d'un coup d'œil ce qui demande une action (invitation qui expire, essai qui se
    termine, entreprise suspendue, système en panne) : dès l'ouverture, sans naviguer.
Si l'interface la plus belle rend l'un de ces parcours plus long que la valeur de D0, c'est
le design qui cède.

D2. Backend (le strict nécessaire, sous le rôle coges_app_platform)
Migration au prochain numéro libre ; écris les GRANT colonne par colonne comme en 0026 et
mets à jour test_platform_role_grants et T37 (TABLES_WITHOUT_RLS).
- Table platform_invitations (hors RLS, aucune colonne company_id) : id, email (stocké en
  minuscules), display_name, role, token_hash (sha256 ; le jeton n'est JAMAIS stocké ni
  journalisé en clair), invited_by, created_at, expires_at (72 h), accepted_at, revoked_at.
  Index unique partiel : une seule invitation en attente par e-mail. Une invitation est
  « en attente » tant que ni acceptée, ni révoquée, ni expirée.
- Routes (toutes sous /api/v1/platform ; lecture : les deux profils ; écriture :
  `administrator` seulement, via require_platform_role, revérifiée en base) :
  * GET  /team : comptes de l'équipe (nom, e-mail, profil, statut actif/suspendu, dernière
    connexion) + invitations en attente (statut « invité », date d'expiration).
  * POST /team/invitations (clé d'idempotence obligatoire : un double clic n'envoie pas deux
    e-mails), POST /team/invitations/{id}/resend (invalide l'ancien jeton, en émet un
    nouveau), DELETE /team/invitations/{id} (révoque).
  * POST /auth/accept-invitation (publique, jeton + mot de passe selon la politique
    existante) : crée le compte, consomme le jeton (usage unique), ouvre une session. Même
    réponse pour jeton inconnu, expiré, révoqué ou déjà utilisé. Freinage par IP comme la
    connexion.
  * PATCH /team/{id} : { role? , is_active? , reason }. Garde-fous, tous testés :
    - on ne modifie jamais son propre compte (profil ni suspension) ;
    - il reste TOUJOURS au moins un administrateur actif (sur le patron du « dernier
      gérant », ADR 0054) : refus 409 avec message clair ;
    - une suspension révoque les sessions du compte (les triggers de 0026 le font déjà :
      prouve-le) ; un changement de profil prend effet à la requête suivante (le profil est
      relu en base, pas lu dans le jeton) ;
    - raison obligatoire pour une suspension ; audit critique pour chaque changement, avec
      avant/après lisibles.
  * GET /users : utilisateurs des commerçants, LECTURE SEULE, toutes entreprises, pages de
    20. Colonnes : nom, e-mail, entreprise (nom + id), rôle(s), statut (actif / désactivé /
    entreprise suspendue), dernière connexion. Filtres : q (nom, e-mail ou entreprise,
    jokers % _ échappés), role, status, company_id ; tri par dernière connexion ou par nom.
    N'utilise QUE les colonnes déjà accordées par 0026 (pas de téléphone, pas de hachage) ;
    un test d'architecture exécute les requêtes sous le vrai rôle pour le prouver.
  * GET /audit : journal des modifications de la plateforme (qui, quoi, quand, sur quelle
    entreprise ou quel compte), filtres acteur, action, entreprise, période, pages de 50,
    `administrator` seulement. Le champ diff passe par une liste blanche de champs : jamais
    de hachage, de jeton ni de mot de passe, même par erreur (test avec une valeur piège).
  * GET /team/summary (ou extension de /stats/overview — choisis le plus simple) : comptes de
    l'équipe (total, actifs, suspendus) et invitations en attente, daté.
  * GET /roles : les deux profils et la liste des capacités de chacun, DÉRIVÉE du code
    (celle que lit require_platform_role), pas écrite à la main. Test-registre : toute route
    /platform qui exige un profil doit figurer dans cette liste ; une route ajoutée plus
    tard et non classée fait échouer la CI.
- E-mails : SMTP par variables d'environnement (lot 1), envoyés APRÈS le COMMIT, jamais
  si l'écriture échoue (test d'échec au COMMIT, ADR 0079). Sans COGES_SMTP_HOST : l'invitation
  est créée, rien ne part, l'écran de l'invitation l'indique (« e-mail non configuré ») et
  propose de copier le lien UNE fois. Le lien pointe vers l'adresse publique de
  l'administration (variable d'environnement existante si elle existe, sinon nouvelle,
  documentée dans README-infra.md et coges.env.example).
- make create-platform-user reste la voie du premier administrateur et de secours.

D3. Thème et coque (frontend-admin/)
- Reprends les jetons de la maquette v2 de frontend/app/globals.css : vert de la marque, fond
  papier, une couleur par rubrique, Figtree hébergée (next/font/local, licence OFL, copie
  des fichiers), clair ET sombre comme l'app commerçante. Copie ce qu'il faut dans
  frontend-admin/ (pas d'import entre applications : elles restent déployées séparément).
  Mêmes noms de jetons qu'en frontend/, pour qu'un futur partage reste possible.
- Repère « Administration » : bandeau fin et permanent en haut de chaque écran (étiquette
  « Administration » + profil connecté), dans une couleur de rubrique réservée à
  l'administration (choisis-la et dis laquelle dans l'ADR), titre d'onglet préfixé
  « Administration · » et favicon distinct. Il doit rester visible sur mobile.
- Garde-fou : reprends lib/no-hardcoded-colors.test.ts pour frontend-admin/ (aucune couleur en
  dur dans app/ et components/).
- Coque : menu latéral à gauche dès 1024 px, avec groupes « Accès » (Tableau de bord,
  Entreprises, Utilisateurs, Équipe, Journal) et « Plateforme » (Statistiques, Système,
  Tâches) ; pastille rouge sur Système quand le bilan est en panne (le bandeau existant
  reste). En dessous de 1024 px : barre du haut avec bouton « Menu » qui ouvre un tiroir
  (focus piégé, Échap, retour du focus). Page courante marquée par aria-current.
- Icônes : une seule bibliothèque, la même que frontend/ si elle y est (vérifie
  package.json), sinon lucide-react en version figée, importée icône par icône ; chaque icône
  seule porte un nom accessible.
- Typographie lisible (15 px minimum pour un texte courant), espaces généreux, cibles
  tactiles de 44 px, couleurs discrètes : la couleur ne sert qu'aux statuts et à l'action
  principale de la page.

D4. Écrans
 a. Tableau de bord (page d'accueil, remplace la redirection actuelle vers /companies) :
    - Tuiles « Équipe » : comptes, actifs, suspendus, invitations en attente ; tuiles
      « Commerçants » : entreprises actives, en essai, suspendues, comptes commerçants actifs
      (réutilise /stats/overview ; le revenu reste sur Statistiques). Chaque tuile est un lien
      vers la liste déjà filtrée. Chaque chiffre est daté.
    - Bloc « À traiter » (D1.6) : invitations qui expirent dans 24 h, essais qui se terminent
      dans 7 jours, entreprises suspendues, bilan système en panne ; vide = message
      rassurant, pas un bloc vide.
 b. Utilisateurs (/users) : tableau (nom, entreprise, rôle, statut, dernière connexion, action
    rapide « Voir l'entreprise »). Recherche + filtres rôle/statut/entreprise en puces, état
    DANS L'ADRESSE (?q=&role=&status=&company=&page=) pour qu'un lien se partage. Saisie
    différée de 300 ms, squelette de chargement, état vide qui dit quoi faire, tri par
    en-tête avec aria-sort. Dernière connexion en relatif (« il y a 3 jours ») avec la date
    exacte en infobulle accessible. Sous 768 px : cartes à la place du tableau.
    Rappel visible : « Lecture seule — les comptes des commerçants sont gérés par leur gérant ».
 c. Équipe (/team) : tableau (nom, e-mail, profil, statut actif / suspendu / invité, dernière
    connexion, actions). Bouton « Inviter un collègue » (nom, e-mail, profil, avec une phrase
    qui dit ce que le profil permet). Actions par ligne : Changer le profil, Suspendre /
    Réactiver ; pour une invitation : Renvoyer, Annuler. Panneau « Ce que peut chaque profil »
    alimenté par GET /roles. Le profil Support voit la liste sans aucun bouton d'action
    (cachés côté écran, refusés côté serveur). Sa propre ligne n'a ni « Suspendre » ni
    « Changer le profil », avec une aide qui dit pourquoi.
 d. Journal (/audit) : qui, quoi, quand, sur qui. Phrases lisibles en français (« Aïssatou D.
    a passé Moussa B. de Support à Administrateur »), pas de JSON brut ; filtres acteur,
    action, entreprise, période ; lien « Historique » depuis chaque fiche entreprise et
    chaque ligne d'équipe qui ouvre le journal déjà filtré.
 e. Page d'invitation (/invitation/[jeton], hors coque, thème CoGes) : choix du mot de passe
    avec la règle affichée avant l'erreur, message unique pour tout jeton invalide, redirection
    vers le tableau de bord à la réussite.
 f. Entreprises et fiche : même contenu et mêmes actions (suspension, abonnement, accès
    support) dans le nouvel habillage ; puces de statut cliquables pour filtrer ; cartes sous
    768 px ; sections de la fiche sobres, l'action de suspension isolée et clairement
    nommée.
 g. Statistiques, Système, Tâches : nouvel habillage seulement, AUCUN changement de logique
    ni de chiffre.

D5. Actions sensibles
- Généralise StatusDialog en un composant de confirmation unique : titre qui nomme la cible,
  conséquence en mots simples (« Moussa B. ne pourra plus se connecter ; ses sessions
  s'arrêtent à la prochaine requête »), raison obligatoire pour suspendre, bouton de
  confirmation à l'étiquette explicite (« Suspendre Moussa B. », pas « OK »), bouton Annuler
  préfocalisé pour les actions destructrices. Échap annule, le focus revient au bouton
  d'origine, bouton désactivé pendant l'appel (pas de double envoi).
- Après l'action : confirmation visible avec lien « Voir dans le journal », ou erreur claire
  qui dit quoi faire. Jamais de message technique ni de trace.
- Réactiver et inviter demandent une confirmation légère (sans raison) ; renvoyer une
  invitation n'en demande pas.

D6. Tests (rouge d'abord)
- Backend : cycle de vie d'une invitation (créée, jeton haché en base, acceptée une seule
  fois, expirée refusée, révoquée refusée, renvoyée = ancien jeton mort, même réponse pour
  tous les jetons invalides) ; garde « dernier administrateur » ; refus de se modifier soi-
  même ; Support ne peut aucune écriture ; changement de profil effectif à la requête
  suivante ; suspension = sessions révoquées ; /users ne renvoie que des colonnes accordées
  et échappe les jokers ; /audit exclut tout secret ; e-mail jamais envoyé sur échec au COMMIT ;
  test-registre de /roles ; aucun droit nouveau sur une table de commerçant (test existant
  étendu).
- Frontend (Vitest) : filtres synchronisés avec l'adresse, tri, état vide, cartes mobiles,
  dialogue de confirmation (raison, focus, double clic), profil Support sans actions,
  garde-fou de couleurs.
- E2E (Playwright, base coges_e2e) : un parcours par tâche de D1 avec son nombre de clics
  maximum ; invitation complète (envoi capturé, acceptation, connexion) ; axe 0 violation en
  clair ET en sombre sur chaque écran ; viewport 360 px sans défilement horizontal ; clavier
  seul pour inviter et suspendre.
- make admin-check, make admin-e2e, suite backend complète, ruff, mypy, shellcheck, CI verte,
  Lighthouse accessibilité ≥ 95 sur la connexion et le tableau de bord.

D7. Fin de lot
- Captures « après » (clair, sombre, mobile) dans docs/design/captures/admin/apres/, et dans
  l'ADR le tableau « tâche : clics avant / après ».
- ADR : amende l'ADR 0089 (thème CoGes + repère), décrit les invitations et les garde-fous,
  la liste des routes /platform par profil, la couleur du repère.
- README de frontend-admin/, README-infra.md et coges.env.example (variables SMTP et adresse
  publique), docs/runbooks/administration.md en français simple (inviter, retirer un
  accès, retrouver qui a fait quoi, perte du dernier administrateur → make
  create-platform-user), CLAUDE.md §8 et table des ADR.

Hors lot, volontairement : modifier ou désactiver un compte de commerçant, permissions
cochables par compte, suppression définitive d'un compte, invitations pour les commerçants,
authentification à deux facteurs (à proposer comme lot suivant si je le demande).
```

## Ce que le propriétaire fait lui-même

1. **Avant le déploiement** : vérifier que les variables SMTP (`COGES_SMTP_*`) sont dans `/etc/coges/coges.env` ; sans elles, les invitations sont créées mais aucun e-mail ne part (le lien peut alors être copié à la main).
2. **Après le déploiement** : se connecter, inviter un collègue de test, accepter l'invitation, suspendre puis réactiver ce compte, et lire le journal.
3. **Regarder les captures avant/après** et dire si le repère « Administration » est assez visible sans être agressif.
4. Garder au moins **deux administrateurs actifs** : le garde-fou empêche d'en retirer le dernier, mais pas d'oublier son mot de passe.
