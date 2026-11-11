# Prompt 36 — Groupe 5 : corriger une vente, notifications sur le téléphone, photo d'article

Branche de départ : `main` à jour, après le déploiement du groupe 2. Décision du propriétaire (11 novembre 2026) : le groupe 5 passe avant les groupes 3 (vente en gros) et 4 (devis). Règle : ce groupe est testé, fusionné et déployé avant le suivant. Une PR par bloc, dans l'ordre R, N, I, A.

Décisions du propriétaire :
- **Corriger une vente** (« Annuler et refaire ») : pendant **10 minutes** après l'encaissement, par **toute personne qui peut vendre**.
- **Notifications** : sur le téléphone, même application fermée, après un appui sur « Activer les notifications » puis l'autorisation du téléphone. L'écran verrouillé montre **le détail utile, sans aucun montant**.
- **Photos d'article** : stockées chez **Cloudinary** (compte créé par le propriétaire).

```
Groupe 5 (depuis main à jour). Règles habituelles : ADR au prochain numéro libre, tests
d'abord (rouge puis vert), ne jamais ouvrir ni commiter .env, deploy/.env.preprod ni
backend/.vercel/. Résumé en français à la fin, questions ouvertes par AskUserQuestion.
Migrations : ajouts seuls, rétrocompatibles (ADR 0083). Une PR par bloc : R, N, I, A.
Services externes autorisés pour ce groupe : Cloudinary (photos, compte du propriétaire) et
les services de notification des navigateurs (Web Push) ; aucun autre.

R. Corriger une vente : « Annuler et refaire » pendant 10 minutes (PRIORITAIRE, touche l'argent)
- Sur le détail d'une vente confirmée, et sur l'écran de succès après l'encaissement, bouton
  « Corriger cette vente » avec le temps restant (« encore 7 min »), visible pour qui a le
  droit de vendre (sales:create + sales:confirm), dans les 10 minutes qui suivent la
  confirmation (heure du SERVEUR, jamais celle du téléphone). Après : bouton absent, et le
  serveur refuse (409 `correction_window_closed`). Le délai est une constante documentée.
- Le geste, en UNE transaction, sous les verrous dans l'ordre existant (dette → vente →
  stock, ADR 0062, 0088) :
  1. vérifier : vente confirmée, dans le délai, aucun retour, aucun encaissement ou lettrage
     fait APRÈS la confirmation, pas déjà corrigée ; sinon refus clair (« Cette vente a déjà
     un retour : faites plutôt un retour ») ;
  2. annuler la vente avec le motif « Corrigée », en réutilisant la logique d'annulation
     existante (stock rendu, dette de la vente fermée) ; contrairement à l'annulation du
     gérant, les paiements faits À LA CONFIRMATION sont annulés d'office par contre-écriture
     (ADR 0038), marqués « correction » ;
  3. créer un NOUVEAU brouillon avec le même client et les mêmes lignes (quantités, remises,
     prix changés et motifs du groupe 1), relié à l'ancienne vente (`corrects_sale_id`) ;
  4. audit critique (qui, quand, quelle vente, quel brouillon), événements outbox habituels.
  Puis l'écran ouvre ce brouillon : la personne corrige et encaisse normalement (nouveau
  numéro de vente à la confirmation, comme toute vente).
- Ce que ce geste n'est PAS : il ne donne pas le droit général d'annuler (sales:cancel reste
  au gérant, à tout moment, avec ses règles actuelles) ; il ne fait sortir aucun argent.
- Caisse : l'annulation du paiement puis le nouvel encaissement apparaissent tous deux,
  marqués « correction », et le journal de caisse et le tableau de bord en tiennent compte
  sans double compte (test : une vente corrigée laisse la caisse du jour au bon montant).
- Brouillon abandonné : si la personne ne réencaisse pas, l'ancienne vente reste annulée et
  le brouillon reste dans « Nouvelle vente » (comme aujourd'hui) ; l'écran le dit avant de
  confirmer le geste (« La vente n° 42 sera annulée. Vous referez l'encaissement. »).
- Traçabilité : l'ancienne vente affiche « Corrigée — remplacée par la vente n° 43 » (ou
  « en cours de correction » tant que le brouillon n'est pas encaissé) ; ses PDF portent
  « ANNULÉE — corrigée ». Le gérant reçoit l'alerte « sale_cancelled » existante, avec
  « corrigée par Awa » : une correction n'est jamais silencieuse.
- Double appui : clé d'idempotence (ADR 0027) ; deux personnes en même temps : la seconde
  reçoit « déjà corrigée » avec le lien vers le nouveau brouillon.
- Tests : dans le délai et juste après (horloge figée), payée comptant, payée en partie, à
  crédit, avec prix changé, avec retour (refus), avec encaissement de dette après (refus),
  vendeur qui corrige la vente d'un collègue (permis), comptable (refusé), deux en même
  temps, caisse et stock exacts après correction et après réencaissement, isolation entre
  entreprises ; e2e de bout en bout sur téléphone (360 px).

N. Notifications sur le téléphone (Web Push)
- Standard Web Push avec clés VAPID (bibliothèque Python libre, version figée, par exemple
  pywebpush). Clés en variables d'environnement (COGES_VAPID_PUBLIC_KEY,
  COGES_VAPID_PRIVATE_KEY, COGES_VAPID_SUBJECT) ; la clé privée ne quitte jamais le serveur ;
  check_runtime_env les vérifie ; sans elles, le bouton n'apparaît pas et rien n'échoue.
  Donne dans le runbook la commande pour générer les clés.
- Table `push_subscriptions` (entreprise, personne, endpoint, clés p256dh et auth, appareil
  lisible, dates, échecs) sous RLS, endpoint unique, quelques appareils au plus par personne.
- Bouton « Activer les notifications » dans le menu du compte : la permission du navigateur
  n'est demandée QU'après cet appui. « Désactiver » sur le même écran. Sur iPhone, les
  notifications ne marchent que si CoGes est installé sur l'écran d'accueil : le dire, avec
  l'aide d'installation existante (ADR 0102). Refus du navigateur : message clair et
  comment réautoriser.
- Ce qui est envoyé : chaque alerte qui arrive dans la cloche de la personne (mêmes types,
  mêmes destinataires, mêmes droits qu'aujourd'hui), envoyée par le worker APRÈS le COMMIT,
  jamais dans la requête. Regroupe les rafales (plus de 3 alertes en 1 minute : une seule
  notification « 4 nouvelles alertes »). Pas de notification pour les alertes de la
  personne elle-même qui vient d'agir quand c'est évident (à proposer dans l'ADR).
- Contenu (décision : détail utile, SANS MONTANT) : titre et texte écrits par le serveur, par
  type — ex. « Riz 25 kg : stock bas (3 sacs) », « Riz 25 kg est épuisé », « Dette de
  Moussa D. arrivée à échéance », « Vente n° 42 annulée par Awa », « Fin de l'essai dans
  3 jours », « Accès support ouvert par l'équipe CoGes ». Aucun montant d'argent, aucun
  numéro de téléphone. Test qui échoue si un texte de notification contient un montant.
  Le toucher ouvre l'écran concerné (chemin relatif de l'application, vérifié côté worker
  et côté service worker).
- Service worker (ADR 0102) : gestionnaires `push` et `notificationclick` ajoutés, sans
  rien changer à la règle « aucune donnée en cache ». Déconnexion : l'abonnement de cet
  appareil est supprimé (serveur et navigateur). Réponse 404/410 d'un service de push :
  abonnement supprimé. Plafond d'envois par personne et par heure.
- L'administration (frontend-admin/) n'est pas concernée.
- Tests : abonnement et désabonnement, isolation, contenu sans montant pour chaque type,
  regroupement, 410 qui supprime, déconnexion qui supprime, service worker (Vitest dans un
  faux environnement), e2e (Chromium : permission accordée, push simulé, clic qui ouvre le
  bon écran).

I. Photo d'un article (Cloudinary)
- Compte Cloudinary du propriétaire : COGES_CLOUDINARY_CLOUD_NAME, COGES_CLOUDINARY_API_KEY,
  COGES_CLOUDINARY_API_SECRET en variables d'environnement ; le secret ne va JAMAIS au
  navigateur ; check_runtime_env les vérifie ; sans elles, la photo est simplement
  indisponible (aucune erreur).
- Envoi par le SERVEUR (recommandé, à confirmer avec moi si tu proposes l'envoi direct
  signé depuis le navigateur) : le front envoie l'image à l'API ; l'API la vérifie et la
  ré-encode comme le logo (ADR 0111 : type lu dans le contenu, SVG refusé, GPS et
  métadonnées retirés, bombe refusée, 1600 px de côté au plus, 5 Mo au plus envoyés), puis
  la dépose chez Cloudinary dans un dossier par entreprise, sous un identifiant aléatoire
  (jamais le nom de l'article, jamais devinable). Le navigateur ne parle jamais à l'API
  Cloudinary.
- Données : colonnes sur products (identifiant Cloudinary, version, dimensions) ou petite
  table sous RLS, au choix justifié. Audit de l'ajout, du changement et du retrait.
- Prise de vue : « Prendre une photo » (caméra arrière, `capture`) et « Choisir une image »,
  dans Nouvel article, Modifier l'article et la fiche ; aperçu ; « Retirer ». Droits :
  products:create / products:update.
- Affichage : fiche (grande), liste du Stock et grille de vente (petites vignettes, chargées
  à la demande, taille réduite par une transformation Cloudinary : format et qualité
  automatiques, largeur adaptée) ; sans photo, le carré coloré actuel reste. Pas sur les
  reçus. CSP : `img-src` gagne seulement https://res.cloudinary.com ; rien d'autre.
- Retrait et suppression d'article : l'image est supprimée chez Cloudinary par le worker
  après le COMMIT, avec nouvelles tentatives ; un balayage de nuit retire les images
  orphelines du dossier de l'entreprise.
- Le service worker ne garde pas les photos (autre origine, et règle « aucune donnée »).
- Documente dans l'ADR et le runbook : les photos ne sont pas dans la sauvegarde chiffrée
  (elles sont chez Cloudinary) ; ce qui arrive si le compte Cloudinary est perdu (les
  articles restent, sans photo) ; la surveillance du quota du plan Cloudinary ; Cloudinary
  est un sous-traitant à citer dans la politique de confidentialité (lot Pages légales).
- Tests : avec un faux client Cloudinary (aucun appel réseau en CI) : envoi, ré-encodage,
  métadonnées retirées, SVG refusé, retrait, suppression d'article, orphelins, isolation,
  secret jamais renvoyé par l'API ; e2e (prendre une photo avec un faux flux caméra, voir
  la vignette dans la grille de vente), 360 px, axe.

A. Fin du groupe
Suite backend complète, ruff, mypy, make front-check, make maquette-check, e2e des écrans
touchés, tests de fuite inter-tenant, CI verte, pip-audit. ADR, CLAUDE.md §8, README-infra.md
et coges.env.example (nouvelles variables), runbooks (générer les clés VAPID, configurer
Cloudinary). Liste dans le résumé ce que le propriétaire vérifie après déploiement.
```

## Ce que le propriétaire fait lui-même

1. **Cloudinary** : créer le compte, noter le *cloud name*, la clé et le secret d'API, et les mettre dans `/etc/coges/coges.env` (jamais dans git ni dans une conversation). Vérifier les limites du plan choisi.
2. **Notifications** : générer les clés VAPID avec la commande du runbook et les mettre dans `/etc/coges/coges.env`.
3. Après le déploiement, sur un téléphone :
   - faire une vente, appuyer sur « Corriger cette vente » dans les 10 minutes, corriger et réencaisser ; vérifier la caisse du jour ; vérifier que le bouton disparaît après 10 minutes ;
   - « Activer les notifications », autoriser, puis faire baisser un stock sous son seuil : la notification arrive téléphone verrouillé, sans montant (sur iPhone, CoGes installé sur l'écran d'accueil) ;
   - prendre la photo d'un article et la voir dans la grille de vente.
