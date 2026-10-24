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

## Perte du dernier administrateur

Si plus personne ne peut se connecter en administrateur (mot de passe oublié, départ), sur
le serveur :

```bash
make create-platform-user EMAIL=prenom.nom@exemple.com NAME="Prénom Nom" ROLE=administrator
```

Le mot de passe est demandé à la ligne de commande. Ce compte peut ensuite réactiver ou
réinviter les autres. Gardez **au moins deux administrateurs actifs** : le garde-fou empêche
d'en retirer le dernier, pas d'oublier son mot de passe.
