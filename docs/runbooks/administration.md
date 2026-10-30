# Gérer l'équipe CoGes dans l'administration (ADR 0094, 0105)

L'administration s'ouvre sur `https://admin.<domaine>`. Chaque compte s'y connecte avec son
mot de passe **puis** un code de son téléphone : la double authentification est obligatoire,
pour tout le monde, sans exception (ADR 0105). Deux profils, fixes :

- **Administrateur** : gère l'équipe, suspend une entreprise, change une offre, enregistre
  un paiement, ouvre un accès support, lit le journal.
- **Support** : consulte (entreprises, comptes, statistiques, système) et ouvre un accès
  support en lecture seule. Ne modifie ni l'équipe ni les abonnements, ne lit pas le
  journal.

L'écran **Équipe → Ce que peut chaque profil** donne la liste exacte, tirée du code.

## Inviter un collègue

1. **Équipe → Inviter un collègue**.
2. Nom, e-mail, profil. La phrase sous le profil dit ce qu'il permet.
3. **Envoyer l'invitation.** Le collègue reçoit un e-mail avec un lien valable **72 heures,
   une seule fois**. Il y choisit son mot de passe (12 caractères au moins), **enrôle sa double
   authentification** (voir plus bas), range ses codes de secours, puis arrive au tableau de
   bord.

Sans e-mail configuré (`COGES_SMTP_HOST` vide) : l'invitation est créée, rien ne part, et le
lien s'affiche **une fois**. Copiez-le et transmettez-le vous-même, par un canal sûr. Il ne
sera plus montré : s'il est perdu, **Renvoyer** en crée un nouveau (l'ancien ne sert plus).

Un lien expiré, annulé, déjà utilisé ou remplacé affiche le même message : « Ce lien
d'invitation n'est plus valable ». Renvoyez l'invitation.

## Retirer un accès

- **Suspendre** (ligne du collègue → Suspendre, avec la raison) : il ne peut plus se
  connecter, et ses sessions s'arrêtent à sa prochaine action. Son compte et son historique
  restent. **Réactiver** le rend.
- **Changer le profil** : un administrateur passé en Support perd la gestion dès sa
  prochaine action, sans se reconnecter.
- Une invitation pas encore acceptée : **Annuler**.

On ne peut ni se suspendre ni changer son propre profil : demandez-le à un autre
administrateur. Et il reste **toujours au moins un administrateur actif** : l'action qui
retirerait le dernier est refusée.

## Double authentification (ADR 0105)

### Enrôler son téléphone

À la première connexion après la mise en service (ou en acceptant une invitation, ou après
une réinitialisation), l'administration demande d'abord d'enrôler son téléphone. Rien d'autre
n'est accessible avant la fin.

1. Installer une application d'authentification : Google Authenticator, Microsoft
   Authenticator, Aegis (Android), ou celle de son gestionnaire de mots de passe.
2. Dans l'application, **ajouter un compte** en scannant le QR code. Sans appareil photo :
   saisir la clé texte affichée dessous (type « basé sur le temps »).
3. Saisir le code à 6 chiffres que l'application affiche → **Activer la double
   authentification**. Un code refusé : vérifier que l'heure du téléphone est automatique.
4. **Les dix codes de secours** s'affichent, **une seule fois** : **Imprimer** ou **Copier**
   dans son gestionnaire de mots de passe, loin du téléphone, cocher « J'ai rangé ces codes en
   lieu sûr », puis **Continuer**.

Ensuite, chaque connexion : e-mail et mot de passe, puis le code du moment. Une session dure
**12 heures au plus**, et se ferme après **1 heure sans activité**.

Chaque connexion depuis un **nouvel appareil** (un autre navigateur, ou un navigateur dont les
cookies ont été effacés) est notée au **Journal**, apparaît dans **À traiter** pendant 7 jours,
et part par e-mail à la personne (et à `COGES_PLATFORM_ALERT_EMAIL`) quand le SMTP est
configuré. Une connexion inconnue de vous : prévenez un autre administrateur, qui réinitialise
votre double authentification.

### Codes de secours

- Sur l'écran du code : **Utiliser un code de secours**, puis saisir un des dix codes
  (`ABCD-EFGH`, majuscules ou minuscules). Chaque code ne sert **qu'une fois**.
- Un code de secours utilisé est noté au journal, signalé dans **À traiter** et par e-mail.
- **Ma sécurité** (menu) : combien il en reste, et **Générer de nouveaux codes de secours**
  (le code de l'application est demandé). Les anciens ne servent plus dès que les nouveaux
  s'affichent.

### Téléphone perdu ou changé

1. La personne prévient **un autre administrateur**, par un canal où il la reconnaît (appel,
   en personne) : jamais sur la seule foi d'un e-mail.
2. L'administrateur : **Équipe** → ligne du collègue → **Réinitialiser le code**, avec la
   raison. Les sessions du collègue s'arrêtent tout de suite, ses codes de secours ne servent
   plus ; la ligne affiche « Code à activer ».
3. À sa connexion suivante, le collègue enrôle son nouveau téléphone (étapes ci-dessus).

On ne réinitialise jamais sa propre double authentification. **Dernier recours** (plus aucun
administrateur capable de se connecter), sur le serveur :

```bash
docker compose -p coges exec api python -m app.cli reset-platform-mfa --email prenom.nom@exemple.com
```

Même effet, noté au journal « en ligne de commande ». Au besoin, faites-le suivre de
`create-platform-user` (section « Perte du dernier administrateur »).

### La clé `COGES_MFA_ENCRYPTION_KEY`

Elle chiffre les secrets des téléphones et signe les codes de secours. Sans elle, l'API ne
démarre pas.

- **Création** (une fois) : `openssl rand -base64 32 | tr '+/' '-_'`, posée dans
  `/etc/coges/coges.env` (et `preprod.env`, avec une **autre** valeur).
- **Rangement** : comme la clé privée **age** de la sauvegarde (`docs/runbooks/sauvegarde.md`)
  — dans le gestionnaire de mots de passe **et** en copie hors ligne. Elle n'est jamais
  commitée, jamais envoyée par messagerie.
- **Restauration d'une sauvegarde** : la base restaurée garde les secrets chiffrés ; il faut
  **la même clé** pour qu'ils servent. Restaurer sans elle revient au cas « clé perdue ».
- **Clé perdue** (ou changée) : les secrets et les codes de secours deviennent illisibles ;
  personne ne peut plus passer l'étape du code. Procédure :
  1. tirer une nouvelle clé, la poser dans `coges.env`, la ranger comme ci-dessus ;
  2. redéployer la version en place (`sudo -u deploy /opt/coges/deploy.sh production
     $(cat /opt/coges/state/production.version)`) ;
  3. pour **chaque** membre de l'équipe : `app.cli reset-platform-mfa --email …` (commande
     ci-dessus) ;
  4. chacun réenrôle son téléphone à sa connexion suivante et range ses nouveaux codes.

### Passer l'administration en mode `mfa` sur le VPS

Le mode `mfa` sert `admin.<domaine>` sur 443 à toute adresse : la double authentification est
la barrière. `deploy.sh` refuse ce mode avec une version qui ne l'impose pas.

1. DNS : `admin.<domaine>` en enregistrement **A** vers l'adresse du VPS, « DNS only »
   (pas de nuage orange). En venant du mode `cloudflare`, supprimer d'abord la route publique
   du tunnel dans Zero Trust.
2. Dans `/etc/coges/coges.env` : `COGES_MFA_ENCRYPTION_KEY=…` (section ci-dessus),
   `COGES_ADMIN_GATE=mfa`, et **vider** `COGES_ACCESS_TEAM_DOMAIN` et `COGES_ACCESS_AUD`.
   `COGES_ADMIN_ALLOWED_IPS` est ignoré.
3. Installer les scripts du VPS de la version si `deploy.sh` le demande
   (`docs/runbooks/deploiement.md`), puis déployer :
   `sudo -u deploy /opt/coges/deploy.sh production vX.Y.Z`. `cloudflared` s'arrête seul.
4. Vérifier : `https://admin.<domaine>/login` répond depuis un téléphone en 4G ; la connexion
   demande le code ; `curl -sI https://admin.<domaine>/login` montre `Strict-Transport-Security`
   et `X-Frame-Options: DENY`.
5. Chaque membre de l'équipe se connecte et enrôle son téléphone.

Retour arrière : `COGES_ADMIN_GATE=ip` (avec `COGES_ADMIN_ALLOWED_IPS`) puis redéployer — c'est
aussi le seul mode possible pour revenir à une version d'avant l'ADR 0105.

## Retrouver qui a fait quoi

- **Journal** (administrateurs) : chaque geste en une phrase (« Aïssatou D. a passé
  Moussa B. de Support à Administrateur »), avec date et heure. Filtres : qui, quoi,
  période.
- Depuis la fiche d'une entreprise ou la ligne d'un collègue : **Historique** ouvre le
  journal déjà filtré.

## Créer une entreprise

L'administration ne crée pas d'entreprise et il n'y a pas d'inscription publique
(ADR 0009) : sur le serveur, une commande crée l'entreprise, ses trois rôles et son
gérant dans une seule transaction. Le gérant a un **e-mail, un téléphone, ou les deux** :

```bash
# Gérant avec e-mail
uv run --directory backend python -m app.cli create-company --name "Boutique Diallo" \
  --slug boutique-diallo --manager-name "Awa Diallo" --manager-email awa@exemple.com

# Gérant sans e-mail : son téléphone, sous n'importe quelle forme
uv run --directory backend python -m app.cli create-company --name "Boutique Sarr" \
  --slug boutique-sarr --manager-name "Fatou Sarr" --manager-phone "+221 77 123 45 67"
```

Le mot de passe du gérant est demandé à la ligne de commande (12 caractères au moins).

Le numéro est ramené à ses chiffres, sans l'indicatif 221 devant un numéro à neuf
chiffres, exactement comme à la connexion : la commande affiche `téléphone=771234567`, et
le gérant se connecte avec le slug et « 77 123 45 67 », « +221 77 123 45 67 » ou
« 221771234567 », au choix. Le même numéro peut servir dans deux entreprises : ce sont
deux comptes distincts, départagés par le slug.

Refus, sans rien créer :

- ni e-mail ni téléphone : « Donnez un e-mail ou un numéro de téléphone. » ;
- numéro de moins de 6 ou de plus de 15 chiffres : « Ce numéro de téléphone n'est pas
  valide. » ;
- e-mail mal formé : « Adresse e-mail invalide : … » ;
- slug déjà pris : erreur d'unicité sur `companies`, choisissez un autre slug.

## Perte du dernier administrateur

Si plus personne ne peut se connecter en administrateur (mot de passe oublié, départ), sur
le serveur :

```bash
make create-platform-user EMAIL=prenom.nom@exemple.com NAME="Prénom Nom" ROLE=administrator
```

Le mot de passe est demandé à la ligne de commande. Ce compte peut ensuite réactiver ou
réinviter les autres. Gardez **au moins deux administrateurs actifs** : le garde-fou empêche
d'en retirer le dernier, pas d'oublier son mot de passe.
