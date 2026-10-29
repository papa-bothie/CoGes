# Prompt 32 — Correctifs de la relecture des lots 28, 29 et 31

Branche `fix/review-28-29`, depuis `main` à jour. Relecture en lecture seule faite le 29 octobre 2026 des ADR 0096 à 0102 et du code correspondant. Rien n'a été exécuté : chaque point doit **d'abord être reproduit par un test rouge**, puis corrigé ; un point non reproduit est noté tel quel dans l'ADR, sans changement.

```
Correctifs de la relecture des lots 28, 29 et 31 (branche fix/review-28-29, depuis main à jour).
Règles habituelles : ADR au prochain numéro libre, tests d'abord (rouge puis vert), aucun
service payant, ne jamais ouvrir ni commiter .env, deploy/.env.preprod ni backend/.vercel/.
Résumé en français à la fin, questions ouvertes par AskUserQuestion. Une PR par bloc (R, D, B, P).
Tableau final dans l'ADR : point / reproduit ou non / correctif.

R. Brouillons de saisie (ADR 0101) — PRIORITAIRE
R1. Retour réécrit après un envoi réussi, avec une NOUVELLE clé
    return-form.tsx : `createKey.renew()` est appelé dans `mutationFn` juste après la création
    du retour, avant `draft.clear()` (onSuccess). Le rendu provoqué par `renew()` relance
    l'écriture différée (400 ms) : si le remboursement prend plus de 400 ms, le brouillon est
    écrit avec les quantités et la nouvelle clé ; puis `refundKey.renew()` fait un rendu après
    `clear()`, `cleared` ne correspond plus et le brouillon est réécrit. Conséquences :
    « Brouillon retrouvé » à la réouverture, et un second retour si le premier était partiel ;
    si la page meurt pendant le remboursement, le brouillon restauré porte une clé neuve et
    rejoue le retour. Test e2e : retour partiel avec remboursement lent (route interceptée),
    recharger -> aucun brouillon, aucun second retour possible avec l'ancienne saisie.
    Correction attendue : ne renouveler les clés qu'APRÈS un envoi entièrement terminé et
    `clear()`, passer `busy` pendant tout l'envoi (aucune écriture tant que l'envoi n'est pas
    fini), et ne plus réécrire un brouillon une fois `done` posé. Même vérification pour
    sale-editor (clé de vente) et TOUS les écrans de la liste figée de l'ADR 0101.
R2. `unsent` jamais vidé quand on quitte un écran
    use-draft.ts : l'ensemble `unsent` n'est vidé que par `clear()` ou une saisie vide. Une
    saisie abandonnée (composant démonté) garde l'entrée jusqu'au rechargement : la mise à
    jour invisible n'arrive jamais (hasUnsentDrafts vrai). Corrige : `unsent` reflète les
    brouillons ENCORE PRÉSENTS et non expirés dans le stockage pour la personne courante, ou
    est retiré au démontage quand le brouillon est sauvegardé (il sera retrouvé de toute façon).
R3. Session expirée à l'ouverture : brouillons non effacés
    session.ts / drafts.ts : `clearOwnDrafts()` ne fait rien tant que le propriétaire n'est pas
    connu (/auth/me pas encore chargé). Rouvrir l'application avec un rafraîchissement refusé
    laisse les brouillons 24 h. Corrige : mémoriser le dernier propriétaire (sessionStorage ou
    localStorage sous clé dédiée, sans donnée sensible) et effacer à l'expiration ; test e2e.
R4. Déconnexion depuis un autre onglet : le brouillon est réécrit
    use-draft.ts : B reçoit `storage` (null), puis `pagehide` sur la redirection -> `flush()`
    réécrit. Corrige : ne plus écrire après un signal de déconnexion (drapeau global posé par
    onLogoutElsewhere / forgetLocally avant toute redirection) ; test à deux onglets.
R5. `busy` codé à `false` dans sale-editor et absent de return-form : branche-le sur
    l'écriture en cours (isPending), comme l'ADR l'annonce.

B. Mise à jour invisible (ADR 0102)
B1. Deux onglets : celui qui n'a pas activé la nouvelle version reste bloqué
    register.ts / update.ts : quand l'onglet A active la nouvelle version, `registration.waiting`
    devient null dans B mais `waitingSince` n'est pas remis à zéro ; `activateWaiting()` rend
    false et B ne recharge jamais. Le drapeau RELOADED_FOR_CHUNK / RELOADED_FOR_OUTDATED est
    posé AVANT l'échec : les ChunkLoadError suivantes sont ignorées, un 426 affiche la bannière
    sans rechargement. Corrige : si le contrôleur a changé (controllerchange) ou si la version
    du worker actif diffère de celle de la page, recharger au prochain moment sûr ; ne poser le
    drapeau qu'au rechargement effectif. Test à deux onglets.
B2. 426 pendant que le moment n'est jamais sûr (brouillon, écran de vente) : aucune bannière,
    toutes les requêtes échouent. Après N refus (ou X minutes) en 426, afficher la bannière
    SANS recharger d'office.
B3. Moment sûr non revérifié juste avant `reload()` (jusqu'à 5 s d'attente de
    controllerchange) : revérifier isMutating / brouillons / écran de vente au dernier moment.
B4. Vérifie que la détection de fichier introuvable couvre le message de Turbopack (Next 16)
    et pas seulement « ChunkLoadError » ; test avec une vraie erreur de chargement.
B5. Le rechargement automatique de Next lié à `deploymentId` : vérifie s'il peut survenir
    pendant une vente ou une saisie (il n'obéit pas au gestionnaire) ; si oui, documente-le et
    protège la saisie (brouillons) ou désactive ce rechargement au profit du gestionnaire.

P. PWA, cache et fichiers conservés
P1. Fichiers de l'ancienne version : la durée de 14 jours part du mauvais moment
    static-entrypoint.sh : les fichiers de la version précédente ont la date de SON dernier
    démarrage. Si deux déploiements sont espacés de plus de 14 jours, ils sont supprimés dès le
    démarrage de la nouvelle version, au moment même où un écran resté ouvert en a besoin.
    Corrige : noter dans le volume la date à laquelle chaque build cesse d'être courant (fichier
    témoin par build) et purger 14 jours APRÈS cette date. Ne fais jamais échouer le démarrage
    pour un nettoyage (aucun `set -e` fatal sur find/cp ; `cp -n` compatible coreutils récent).
    Tests du script : déploiements espacés de 20 jours, deux le même jour, volume neuf.
P2. Déconnexion = page hors ligne perdue
    caches.ts et sw-source.ts (LOGOUT) suppriment TOUS les caches, y compris
    coges-static-<build> et /hors-ligne ; jusqu'au prochain déploiement, une navigation sans
    réseau montre l'erreur du navigateur. Corrige : vider les caches puis REMETTRE la
    pré-mise en cache (fichiers sans donnée), ou ne vider que ce qui n'est pas la pré-mise en
    cache. Test e2e : déconnexion puis coupure réseau -> page hors ligne.
P3. Page hors ligne : vérifie qu'elle s'affiche avec ses styles quand le réseau est coupé (CSS
    et polices dans la pré-mise en cache ou styles en ligne), sinon corrige.
P4. NEXT_DEPLOYMENT_ID vide au build = worker identique d'un build à l'autre (jamais de mise à
    jour) : le build de production DOIT échouer si la variable est vide ; vérifie que
    deploy.yml la passe (étiquette de l'image).
P5. Mineurs : contrôle `set-cookie` inopérant dans le worker (en-tête jamais visible côté
    Fetch : retire-le ou remplace-le par une vraie règle), identifiant de build échappé
    (`*/` dans un commentaire), `-mtime +14` = 15 jours, Cache-Control réellement servi pour
    /sw.js en build de production (test).

D. Droits (ADR 0099)
D1. « Encaisser une dette » décoché ne retire plus `payments:create`
    rbac/matrix.py : `payments:create` est aussi dans la ligne `sell`. POST /api/v1/payments
    (finance/router.py) n'exige que `payments:create` : un vendeur à qui le gérant a retiré
    « Encaisser une dette » peut encore, par l'API, encaisser une dette et enregistrer d'autres
    paiements (sens choisi par la requête). Reproduis par un test API. Correction à proposer
    AVANT de coder (AskUserQuestion) : par exemple, la caisse n'a pas besoin de payments:create
    (confirm_sale encaisse en interne) -> retirer payments:create de `sell`, ou exiger
    `debts:read` pour un encaissement lettré et un droit distinct pour une sortie d'argent.
    Vérifie aussi ce qu'un vendeur par défaut peut faire aujourd'hui par POST /payments
    (sortie d'argent vers un fournisseur, paiement sans contexte) et dis-le-moi.
D2. Ligne « en partie » qui retient un droit partagé
    rbac/service.py `set_role_abilities` : un rôle réglé avec l'ancienne grille (inventory:create
    + debts:create) voit « Corriger le stock » ET « Gérer les dettes… » en partie ; cocher puis
    décocher « Gérer les dettes… » laisse debts:create (retenu par la ligne stock en partie) et
    la ligne redevient « en partie ». Corrige pour que « un second appui retire la ligne » soit
    vrai, sans jamais ajouter de droit en silence ; test de ce cas exact.
D3. Rôles sur mesure existants portant `company:update` ou `system:read` (autorisés avant
    0099) : écris une requête de contrôle, et si de tels rôles existent, une migration de
    données qui les retire avec audit (ou demande-moi).
D4. Mineurs : docstrings et commentaires « 8 lignes » / droit partagé périmés (matrix.py,
    rbac/router.py) ; verrou (FOR UPDATE) sur le rôle dans set_role_abilities pour deux
    enregistrements simultanés ; écran des droits qui ne recalcule pas « en partie » après la
    mise à jour optimiste.

C. Retours (ADR 0097) — à documenter ou corriger
C1. Retour qui ne peut jamais être réglé : dette passée en perte après un paiement partiel,
    puis retour total -> la compensation est refusée (plus de dette ouverte) et l'argent est
    plafonné à ce qui a été versé : le reste dû du retour ne se règle jamais et reste « à
    régler ». Propose-moi une règle (AskUserQuestion) : par exemple, la part qui correspond à
    la dette abandonnée est soldée « sans argent » (none_due) avec audit.
C2. Annuler un encaissement APRÈS avoir remboursé le retour de la même vente : rien ne refuse,
    on peut avoir rendu plus que ce qui reste versé (le plafond n'est vérifié qu'au
    remboursement). Préexistant : reproduis, puis dis-moi si on refuse l'annulation dans ce cas
    ou si on la laisse avec une alerte.
C3. Performance : la sous-requête de `returnable` (sales/repository.py) agrège toutes les
    lignes de retour de l'entreprise à chaque page ; restreins-la aux lignes de la page.

Fin de lot
Suite backend complète, ruff, mypy, make front-check, make admin-check, make front-pwa-e2e, e2e
des écrans touchés, tests de fuite inter-tenant, CI verte. Mets à jour les ADR 0097, 0099, 0101,
0102 (section « Corrections »), CLAUDE.md §8.
```

## Ce que le propriétaire fait lui-même

1. Répondre aux trois questions que l'agent posera : droit d'encaisser pour le vendeur (D1), retour après une dette abandonnée (C1), annulation d'un encaissement déjà remboursé (C2).
2. Après le déploiement, sur un téléphone : faire un retour partiel avec remboursement, rouvrir l'écran « Retour » de cette vente — aucun « Brouillon retrouvé » ne doit apparaître.
3. Se déconnecter, couper le réseau, rouvrir CoGes : la page « Pas de connexion » doit s'afficher.
