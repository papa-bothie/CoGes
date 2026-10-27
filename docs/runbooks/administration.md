# Gérer l'équipe CoGes dans l'administration (ADR 0094)

L'administration s'ouvre sur `https://admin.<domaine>`, depuis une adresse autorisée.
Deux profils, fixes :

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
   une seule fois**. Il y choisit son mot de passe (12 caractères au moins) et arrive au
   tableau de bord.

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
