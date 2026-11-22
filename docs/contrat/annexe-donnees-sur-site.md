# Annexe — Ce que CoGes installé sur votre PC envoie à CoGes

> Annexe du contrat de licence et de maintenance de CoGes « sur site » (CoGes installé sur le
> PC de la boutique). Version du 22/11/2026. Référence technique : ADR 0129.

## En deux phrases

Votre PC envoie régulièrement à CoGes un **court bilan technique** : « je vais bien », ou
« la sauvegarde a échoué ». C'est ce qui permet à CoGes de voir une panne avant que vous
n'appeliez. Ce bilan ne contient **aucune donnée de votre commerce** : ni vente, ni montant,
ni article, ni client, ni nom de personne, ni numéro de téléphone.

## Quand il est envoyé

- chaque jour, quand vous ouvrez votre session Windows, et à 13 h 00 et 20 h 30 ;
- après chaque sauvegarde de vos données (réussie ou ratée) ;
- après chaque mise à jour de CoGes (réussie ou annulée), et une fois par jour si une mise à
  jour attend depuis plus de 3 jours.

## Vers où

Vers un service de surveillance (Healthchecks.io, ou un service équivalent choisi par CoGes),
par une connexion chiffrée (https). Ce service garde les bilans reçus et prévient CoGes quand un
PC se tait ou signale un problème. Comme tout site Internet, il voit l'adresse Internet de
votre box.

## Ce qui est envoyé, et rien d'autre

| Champ | Ce que c'est |
|---|---|
| `format` | la version du format du bilan |
| `pc` | un numéro tiré au hasard à l'installation, qui désigne votre PC sans dire qui vous êtes ; seul CoGes sait à quel client il correspond |
| `signal` | le sujet : vie du PC, sauvegarde, mise à jour, ou essai |
| `resultat` | « ok » ou « échec » |
| `raison` | en cas d'échec, un code parmi une liste fixe (par exemple « disque plein » ou « Docker arrêté ») |
| `envoye_le` | la date et l'heure de l'envoi |
| `version` | la version de CoGes installée |
| `canal` | le canal des mises à jour (normal ou essai) |
| `maj` | le résultat de la dernière mise à jour |
| `maj_le` | sa date |
| `maj_attente` | une mise à jour prête qui attend, et depuis combien de jours |
| `services_ok` | combien des 9 parties de CoGes vont bien |
| `services_ko` | le nom technique de celles qui ne vont pas |
| `licence` | si la licence est active ou suspendue |
| `offre` | l'offre (Starter, Business ou Premium), sans le contenu du contrat |
| `sauvegarde_le` | la date de la dernière bonne sauvegarde |
| `copie_le` | la date de la dernière copie sur la clé USB |
| `essai` | si le dernier essai de relecture de la sauvegarde a réussi |
| `essai_le` | sa date |
| `disque_go` | la place libre sur le disque |
| `memoire_go` | la mémoire du PC |
| `windows` | la version de Windows |
| `docker` | la version de Docker Desktop |
| `wsl` | la version de WSL |
| `erreurs_24h` | combien d'erreurs CoGes a notées dans ses journaux en 24 heures |

## Ce qui n'est jamais envoyé

Vos ventes, votre chiffre d'affaires, vos montants, vos articles et leurs prix, vos clients,
vos fournisseurs, vos dettes, le nom ou le téléphone de quiconque, le nom de votre boutique,
vos mots de passe, vos sauvegardes et vos fichiers. Rien n'est envoyé **vers** votre PC : CoGes
ne peut pas commander votre PC à distance par ce moyen. Le PC envoie, il n'écoute rien.

## Le fichier de diagnostic et l'aide à distance

- Le raccourci **« Diagnostic CoGes »** crée sur votre Bureau un fichier qui aide CoGes à
  comprendre une panne. Il contient l'état technique de CoGes, ses journaux et la liste de vos
  sauvegardes (avec le code de votre boutique), sans mot de passe. **Il ne part jamais seul** :
  c'est vous qui l'envoyez, par WhatsApp ou par e-mail, si vous le voulez.
- Le raccourci **« Aide CoGes »** ouvre l'Assistance rapide de Windows. CoGes ne voit votre
  écran que si vous lui donnez le code affiché **et** si vous acceptez. Vous voyez tout ce qui
  est fait, et vous pouvez arrêter à tout moment. Rien ne reste installé ou ouvert après.

## Comment l'arrêter

Demandez-le à CoGes, ou faites-le vous-même. Dans le fichier
`C:\CoGes\reglages\support.json`, remplacez `"remontee": true` par `"remontee": false`. Plus
rien n'est envoyé. CoGes ne verra alors plus les pannes de votre PC avant votre appel, et la
maintenance se fera sur votre demande.
