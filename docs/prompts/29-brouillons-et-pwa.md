# Prompt 29 — Brouillons conservés et application installable (PWA)

Branche `feat/drafts-and-pwa`, depuis `main` à jour, après le prompt 28. Deux sujets du même côté de la frontière : ce que l'appareil garde (saisies en cours) et ce qu'il installe (l'application). Ils partagent une règle de sécurité unique : **ce qui reste sur le téléphone ne doit jamais trahir la boutique** si l'appareil est partagé, perdu ou prêté.

Décisions du propriétaire (AskUserQuestion, à ne pas rouvrir) :
- PWA : **installable + page hors ligne + mises à jour**. Pas de lecture hors ligne des données de la boutique, pas de vente hors ligne (ce serait un lot à part : conflits de stock et de caisse).

Constat de départ : le panier d'une vente est déjà un brouillon **côté serveur** (« Nouvelle vente reprend le brouillon du jour », sale-editor.tsx). Mais tout le reste d'une saisie vit en mémoire du composant : client choisi, mode et montant d'encaissement, formulaires de produit, de livraison, de correction de stock, de dépense, de paiement, de retour, de client. Changer d'onglet de l'application, rafraîchir ou laisser le navigateur décharger la page fait tout perdre.

```
Lot « Brouillons conservés et PWA » (branche feat/drafts-and-pwa, depuis main à jour, après
le prompt 28). Règles habituelles : ADR aux prochains numéros libres, tests d'abord (rouge
puis vert), aucun service payant, ne jamais ouvrir ni commiter .env, deploy/.env.preprod ni
backend/.vercel/. Résumé en français à la fin, questions ouvertes par AskUserQuestion.
Lis d'abord frontend/README.md, frontend/proxy.ts, frontend/next.config.ts (CSP), les ADR 0048,
0058, 0064 et 0085, et le dossier AGENTS.md du frontend (cette version de Next a des
changements incompatibles : lis la doc de node_modules/next/dist/docs avant de coder).

P1. Brouillons : une action commencée se retrouve, ailleurs dans l'application comme après
    un rechargement
Conception :
 - Un hook `useDraft(formId, initial)` et un petit magasin `lib/drafts.ts`, adossé à
   localStorage (survit au changement d'onglet, au rechargement et au déchargement de la
   page par le navigateur), jamais sessionStorage seul. Tout accès sous try/catch : le
   stockage peut être absent ou plein, l'écran marche sans.
 - Clé : `coges:draft:v1:<company_id>:<user_id>:<formId>` (+ identifiant de l'objet édité
   pour une modification : produit, client…). Jamais lue par une autre personne ni une autre
   entreprise, même sur le même navigateur. Valeur : champs saisis + horodatage + version du
   schéma du formulaire ; une version inconnue est ignorée, pas appliquée.
 - Écriture différée (≈ 400 ms après la dernière frappe) et à la perte de visibilité de la
   page (`visibilitychange`), pas à chaque touche.
 - Durée de vie : 24 heures sans modification, puis effacé. Effacé à l'envoi réussi, à
   l'annulation explicite, à la déconnexion (toute la liste de la personne) et à l'expiration
   de session. Nettoyage au démarrage de l'application.
 - JAMAIS stocké : mots de passe, codes, jetons, références de moyens de paiement saisies à
   la main. Une liste blanche de champs par formulaire, pas une liste noire ; un test cherche
   dans tout le stockage une valeur piège saisie dans un champ mot de passe.
 - Deux onglets du navigateur ouverts sur le même formulaire : le dernier écrit gagne, via
   l'événement `storage` ; aucune boucle de réécriture ; aucun écrasement d'un envoi en cours.
 - Retrouvé : les champs reviennent remplis et un bandeau discret dit « Brouillon retrouvé »
   avec « Effacer » (jamais une fenêtre bloquante). Le serveur reste l'autorité : un prix,
   un stock, un client ou un produit qui a changé ou disparu depuis est revérifié à l'envoi
   (ligne retirée avec un message clair, jamais envoyée en silence).
 - Clés d'idempotence : si un brouillon contient une clé d'écriture, elle est effacée avec
   lui à l'envoi réussi ; un envoi interrompu puis retrouvé rejoue AVEC LA MÊME clé (jamais
   deux ventes ou deux paiements, ADR 0027, 0085).
Écrans couverts (liste à confirmer par une lecture du code, l'ADR la fige) :
 - Vendre : client choisi, mode d'encaissement, montant reçu, moyen, échéance (le panier reste
   serveur) ;
 - Produit (création et modification), catégorie, client, fournisseur ;
 - Livraison reçue, correction de stock, dépense, paiement / règlement de dette, retour de
   vente (lignes, motif, mode de remboursement) ;
 - Personne (sans mot de passe).
Tests :
 - Vitest du hook : écriture différée, liste blanche, version inconnue ignorée, TTL, échec du
   stockage sans casser l'écran, séparation par personne et par entreprise.
 - E2E : remplir un formulaire, aller sur un autre onglet de l'application, revenir : champs
   présents ; recharger : présents ; envoyer : effacés ; se déconnecter : effacés ; autre
   utilisateur sur le même navigateur : rien ; le champ mot de passe n'est jamais persisté.
 - Une vente à moitié encaissée : retrouvée au retour, une seule vente à la fin.

P2. PWA : installable, page hors ligne, mises à jour contrôlées
Aucune base existante : pas de manifeste, pas de service worker, `public/` ne contient que le
logo. Contraintes :
 - Manifeste via `app/manifest.ts` : nom « CoGes », nom court, `lang: fr`, `display:
   standalone`, `start_url` et `scope` qui ne tombent pas sur une redirection (vérifie
   proxy.ts), couleurs lues dans les jetons de la maquette (le garde-fou
   lib/no-hardcoded-colors.test.ts doit rester vert : si le manifeste exige des valeurs en
   clair, une exception documentée et testée contre les jetons, pas une copie libre).
   Icônes 192, 512 et masquable 512 dérivées du symbole officiel (public/brand), plus
   l'apple-icon existant.
 - Service worker minimal, sans bibliothèque lourde (une seule bibliothèque, version figée et
   justifiée dans l'ADR, si tu en prends une) :
   * il met en cache UNIQUEMENT des fichiers statiques versionnés (`/_next/static`, polices,
     icônes) et une page `/hors-ligne` ;
   * il ne met JAMAIS en cache : l'API (`/api/*`), les pages HTML authentifiées, toute
     réponse avec cookies, `Authorization` ou `Set-Cookie`, les exports et reçus ; aucune
     donnée de la boutique ne touche le Cache Storage (test qui parcourt tous les caches) ;
   * navigation sans réseau : page `/hors-ligne` claire, même ton que l'écran d'erreur
     (ADR 0085), avec « Réessayer » ; les écritures échouent comme aujourd'hui, brouillons
     conservés (P1), aucune file d'attente cachée ;
   * mise à jour INVISIBLE (décision du propriétaire : les utilisateurs ne doivent pas
     s'en apercevoir, aucune bannière, aucune question) : le nouveau worker et la nouvelle
     version se préparent en arrière-plan, puis s'activent à un MOMENT SÛR, jamais en plein
     travail. Un moment sûr = au prochain lancement de l'application, au retour d'un
     passage en arrière-plan de plus de 5 minutes, ou à la prochaine navigation entre deux
     écrans PAR UN LIEN, à condition qu'aucune requête d'écriture ne soit en cours, qu'aucun
     formulaire n'ait de saisie non envoyée (brouillon sale, P1) et qu'aucune vente ne soit
     en cours d'encaissement. Jamais d'actualisation pendant une vente ou une saisie. Si la
     personne reste sur un même écran sans rien saisir plus de 24 heures, activation
     silencieuse à ce moment-là. Une bannière n'apparaît qu'en DERNIER recours, si la version
     installée est refusée par le serveur comme trop ancienne (voir « compatibilité » ci-
     dessous) ;
   * compatibilité entre versions : (1) l'API reste compatible avec la version précédente du
     front au moins 14 jours (additions d'abord, retraits ensuite, ADR 0083) ; un front trop
     ancien est reconnu par un en-tête de version et reçoit une réponse dédiée qui déclenche
     la mise à jour à un moment sûr ; (2) les fichiers du build précédent (`/_next/static`)
     restent servis après un déploiement pendant au moins 14 jours, sinon un écran resté
     ouvert échoue sur un fichier disparu au premier changement de page. Étudie `deploymentId`
     de Next et la conservation des anciens fichiers statiques par le déploiement sur le VPS
     (deploy.sh, Caddy, volume partagé), ADR à l'appui ; (3) toute erreur de chargement d'un
     fichier de l'application (ChunkLoadError) est rattrapée UNE fois par un rechargement
     propre à un moment sûr, sans message technique ;
   * nom du cache dérivé de l'identifiant de build ; les anciens sont supprimés à
     l'activation ; tout est vidé à la déconnexion (message au worker) ;
   * `sw.js` servi sans cache long (Cache-Control: no-cache) et à la racine du périmètre.
 - Exceptions à ajouter au proxy.ts et aux en-têtes : `/manifest.webmanifest`, `/sw.js`,
   icônes et `/hors-ligne` répondent sans connexion et sans redirection vers /login ; CSP :
   `worker-src 'self'`, `manifest-src 'self'` ; vérifie le Caddyfile du VPS
   (deploy/vps) pour qu'il ne réécrive ni ne mette en cache ces fichiers.
 - Installation : sur Android/Chrome, capture de `beforeinstallprompt` et bouton
   « Installer l'application » dans le menu du compte ; invitation discrète UNE fois après
   quelques visites, ignorable, jamais sur la connexion ni pendant une vente. Sur iPhone
   (Safari n'a pas cet événement) : courte aide « Partager, puis Sur l'écran d'accueil ».
   Une fois installée, plus aucune invitation.
 - L'administration (frontend-admin/) n'est PAS une PWA : aucune installation, aucun
   service worker (outil d'équipe, pas de cache sur des appareils personnels). Un test le
   vérifie.
 - Documente dans l'ADR ce que fait et ne fait pas l'application hors ligne, et la
   procédure de purge si un défaut de cache est découvert (version du worker qui vide tout).
Tests :
 - Validation du manifeste (champs requis, icônes présentes aux bonnes tailles, couleurs =
   jetons), e2e en build de production : le worker s'enregistre, la page /hors-ligne
   s'affiche quand le réseau est coupé (Playwright `setOffline`), aucune réponse d'API dans
   Cache Storage après une session complète, déconnexion = caches vides, nouvelle version =
   mise à jour invisible (aucune bannière ni rechargement pendant une écriture en cours, une
   saisie non envoyée ou une vente ; activation au prochain lancement, retour d'arrière-plan
   ou navigation sûre), ancien écran resté ouvert qui change de page après un déploiement
   sans erreur (anciens fichiers toujours servis), front trop ancien refusé puis mis à jour,
   installation proposée puis effacée.
 - Lighthouse (accessibilité ≥ 95) inchangé sur les écrans touchés ; axe 0 violation.

Fin de lot
Suite backend complète, ruff, mypy, make front-check, e2e des écrans touchés, tests de fuite
inter-tenant, CI verte. ADR : liste figée des écrans à brouillon et des champs conservés,
règles de sécurité du stockage et du cache, comportement hors ligne, procédure de purge.
Mets à jour frontend/README.md, docs/runbooks (déployer une version : ce que voit un
utilisateur déjà installé) et CLAUDE.md §8.
```

## Ce que le propriétaire fait lui-même

1. **Après le déploiement**, sur un vrai téléphone : ouvrir `coges.app`, installer l'application (Android : « Installer » ; iPhone : Partager, Sur l'écran d'accueil), puis couper le réseau et vérifier que la page « hors ligne » s'affiche.
2. Commencer une dépense, passer sur Vendre puis revenir : la saisie doit être là. Se déconnecter : elle doit disparaître.
3. Déployer une seconde version pendant qu'un téléphone a l'application ouverte sur une vente en cours : rien ne doit bouger ni s'afficher ; après la vente puis un changement d'écran ou la réouverture de l'application, la nouvelle version doit être là, sans message.
4. Si un téléphone est partagé dans la boutique, rappeler aux personnes de se déconnecter : les brouillons ne sont effacés qu'à ce moment-là (ou après 24 heures).
