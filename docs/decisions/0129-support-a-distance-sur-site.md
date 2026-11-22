# 0129 — Support à distance et remontée d'informations sur site (lot 6)

- **Date** : 2026-11-22
- **Phase** : sur site, lot 6 (`docs/prompt-sur-site/06-support-a-distance.md`), dernier lot
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion, quatre questions, options recommandées)

## Contexte

Jusqu'au lot 5, quand une sauvegarde échoue, qu'une mise à jour revient en arrière ou que le
disque se remplit chez un client, personne chez CoGes ne le sait. Seul le commerçant voit une
notification Windows, et il peut l'ignorer. Pour aider, il faut se déplacer. Ce lot fait parler
le PC (**toujours sortant, jamais entrant**), rassemble un diagnostic sans secret, et ouvre une
prise en main à distance **avec l'accord du commerçant à chaque fois**. Règles du lot : ajouter
seulement, aucune dérogation nouvelle dans `check_protected_paths.py`, pas de changement de
l'application ni d'image nouvelle, la production et le VPS intacts.

## Décisions de l'utilisateur

1. **Les informations arrivent chez un service de pings « homme mort »** : Healthchecks.io
   (compte gratuit au départ, auto-hébergeable plus tard). C'est le même mécanisme que les
   tâches de la production (ADR 0077 : `GET`/`POST <adresse>`, `<adresse>/fail`). On crée un
   « check » par client et par sujet. Il alerte quand un PC se tait ou signale un échec, et son
   tableau de bord montre tous les clients. Aucun code côté serveur, le VPS n'est pas touché.
2. **Trois signaux par client** :
   - `vie` : à l'ouverture de session (tâche « CoGes - démarrage ») **et** à chaque passage de
     la tâche de sauvegarde (13 h 00, 20 h 30). Ce second envoi s'ajoute au prompt : un PC qu'on
     n'éteint jamais ne rouvre pas de session, et passerait sinon pour muet. Réglage du check :
     période 1 jour, tolérance 3 jours (week-ends, fermetures) ;
   - `sauvegarde` : après chaque sauvegarde, à la main ou planifiée. `/fail` si elle échoue, si
     Docker ne répond pas alors qu'une sauvegarde est due, ou si l'essai de relecture rate ;
   - `mise-a-jour` : après chaque application. `/fail` au retour arrière automatique, au retour
     raté, et une fois par jour tant qu'une version attend depuis plus de 3 jours.
3. **Prise en main à distance : l'Assistance rapide de Windows** (Quick Assist), gratuite et
   déjà dans Windows 11. Le commerçant donne un code et accepte à chaque séance, et rien ne
   reste ouvert. Le script ne l'installe pas et ne la lance pas seul. Le raccourci « Aide CoGes »
   l'ouvre et affiche le numéro de CoGes ; si elle manque, il ouvre sa page du Microsoft Store.
4. **Le diagnostic va sur le Bureau** (`CoGes-diagnostic-AAAAMMJJ-HHMM.zip`). Le commerçant
   l'envoie par WhatsApp ou par e-mail. Aucun fichier n'est envoyé automatiquement.

## Ce qui sort du PC : la liste exacte

La **seule** liste est `deploy/onprem/support/champs.txt`. Elle donne un nom par champ, une règle
pour sa valeur (expression régulière ancrée) et une description. Le script la relit à chaque
envoi (`Get-CogesReport`) : un champ en plus ou en moins, ou une valeur hors de sa règle, et
rien ne part. La CI relit chaque corps reçu avec la même liste
(`deploy/onprem-ci/controle_remontee.py`). Un test vérifie que ce tableau et l'annexe du
contrat (`docs/contrat/annexe-donnees-sur-site.md`) nomment exactement les mêmes champs, dans
le même ordre.

| Champ | Valeurs possibles | Ce que c'est |
|---|---|---|
| `format` | `COGES-RESUME-1` | version du format |
| `pc` | 32 caractères hexadécimaux | identifiant du PC tiré au hasard à l'installation (`reglages\support.json`) ; ni nom, ni code de boutique. La correspondance avec le client reste chez CoGes |
| `signal` | `vie`, `sauvegarde`, `mise-a-jour`, `test` | sujet de l'envoi |
| `resultat` | `ok`, `echec` | ce qui s'est passé |
| `raison` | liste fermée de 13 codes (`place-disque`, `docker-arrete`, `retour-arriere`…) | code de l'échec ; le message lui-même reste dans les journaux du PC |
| `envoye_le` | date et heure | heure du PC à l'envoi |
| `version` | `vX.Y.Z` | version installée |
| `canal` | `stable`, `test` | canal des mises à jour |
| `maj` | `aucune`, `reussie`, `revenue`, `revenue-a-la-main` | dernière mise à jour |
| `maj_le` | date | date de la dernière mise à jour |
| `maj_attente` | `vX.Y.Z depuis N j` | version prête qui attend |
| `services_ok` | `N/9` | services en bonne santé |
| `services_ko` | noms techniques (`api`, `beat`…) | services qui ne le sont pas |
| `licence` | `active`, `essai`, `impayee`, `suspendue`, `aucune` | état de la licence |
| `offre` | `starter`, `business`, `premium` | offre, sans note de contrat |
| `sauvegarde_le` | date | dernière bonne sauvegarde |
| `copie_le` | date | dernière copie hors du PC |
| `essai` | `ok`, `echec`, `jamais` | dernière restauration d'essai |
| `essai_le` | date | sa date |
| `disque_go` | nombre | Go libres sur le disque de CoGes |
| `memoire_go` | nombre | mémoire du PC |
| `windows` | numéro de version | version de Windows |
| `docker` | numéro de version | version de Docker Desktop |
| `wsl` | numéro de version | version de WSL |
| `erreurs_24h` | `sauvegarde=2 mise-a-jour=1`… | lignes ÉCHEC des journaux du PC sur 24 h, par source |

**Ce qui ne sort jamais** : chiffre d'affaires, montant, vente, article, client, fournisseur,
nom de personne, numéro de téléphone, e-mail, nom ou code de la boutique, note de contrat,
mots de passe et clés, adresse IP du réseau du client, fichier (sauvegarde, diagnostic, journal).
Aucune valeur n'est un texte libre : même une raison d'échec est un code de la liste. Le
message complet, qui peut citer un nom de fichier ou une sortie de Docker, reste dans
`C:\CoGes\journaux`. Les règles sont écrites pour qu'aucun nom, numéro de téléphone ou adresse
n'y entre (test `test_no_rule_lets_free_text_through`).

**La licence** se lit par `base.py licence`, une commande nouvelle de l'outil des lots 4 et 5.
Sa requête ne lit que `subscriptions.status`, `plans.code` et `current_period_end IS NULL`,
c'est-à-dire des nombres et des codes d'offre (test qui épingle la requête). Le résumé n'a donc
pas besoin du code de la boutique.

## Ce qui se fait

- **Réglages** : `reglages\support.json` (`format`, `pc`, `remontee`, `adresses` des trois
  checks, `telephone_coges`), **pas** dans `coges.env`, pour ne pas toucher au contrôle du
  lot 1. L'identifiant est tiré par `Installer` ou `Reparer` s'il manque, puis jamais changé.
  `remontee` reste à faux tant que les adresses ne sont pas posées, par `-Support <fichier.json>`
  (préparé chez CoGes) ou par `-Action ConfigurerSupport`. Seules les adresses `https://` sont
  acceptées (`http://127.0.0.1` ou `localhost` pour le faux service des essais).
- **Envoi** (`Send-CogesPing`) : par PowerShell sur l'hôte Windows (les conteneurs restent sans
  Internet), en `POST` du résumé en texte (moins de 2 Ko), vers l'adresse ou vers
  `<adresse>/fail`. Délai de 10 s, 2 essais, et **jamais bloquant** : il rend vrai ou faux et
  n'échoue jamais, un échec va au journal. Si la lecture de l'état échoue, il envoie le résumé
  minimal (valeurs « inconnu »), qui passe lui aussi la liste. La réponse du service n'est pas
  lue, seulement son code HTTP.
- **Les adresses sont des secrets** : `Get-CogesSetting` les ajoute aux valeurs que
  `Mask-Secrets` retire des journaux, et `Etat` ne les montre jamais (« Remontée vers CoGes :
  active (3 adresses), dernier envoi le … »). Dernier envoi et dernier envoi raté sont notés
  dans `C:\CoGes\support\etat.json`.
- **`-Action TesterSupport`** envoie un résumé `signal: test` sur les trois adresses et dit
  laquelle a répondu.
- **Diagnostic** (`-Action Diagnostic` et le raccourci « Diagnostic CoGes ») : la sortie de
  `Etat` et le résumé, `coges ps`, `docker version`, `docker info` abrégé, WSL, Windows ; les
  journaux de `C:\CoGes\journaux` des 7 derniers jours ; les 300 dernières lignes de chaque
  service. Chaque ligne passe par `Mask-Secrets`. On y ajoute `coges.env` réduit aux **noms**,
  `support.json` sans les adresses, la liste des sauvegardes (noms, tailles, dates), le disque,
  la mémoire et les tâches planifiées. Au-delà de 10 Mo, le zip est refait avec 100, puis
  30 lignes par service. Le code de la boutique y paraît (noms des sauvegardes) : ce fichier est
  envoyé par le commerçant lui-même, à CoGes seulement.
- **Aide** (`-Action Aide`, raccourci « Aide CoGes ») : trois phrases (« Appelez CoGes au …,
  donnez le code, acceptez »). Elle ouvre l'Assistance rapide si son paquet
  `MicrosoftCorporationII.QuickAssist` est là, sinon sa page du Store.
- **Journaux bornés** : au début de chaque passage de la tâche de sauvegarde, les fichiers de
  plus de 60 jours sont supprimés, puis le total est plafonné à 200 Mo, les plus anciens
  d'abord. Le journal du jour n'est jamais supprimé. Les journaux Docker l'étaient déjà
  (`max-size: 10m`, `max-file: 3` pour les 13 services, outils des lots 4 et 5 compris). Un
  test le vérifie, et rien n'a été ajouté au compose.
- **Ailleurs, en ajouts** : `Installer` et `Reparer` posent l'identifiant, `-Support` et les deux
  raccourcis. `Etat` gagne les lignes « Remontée » et « Journaux ». `Desinstaller` retire les
  raccourcis et garde `support.json`.

## Écarts au prompt

- **`vie` aussi depuis la tâche de sauvegarde**, en plus de l'ouverture de session (voir
  décision 2).
- **La raison d'un `/fail` est un code**, pas le texte du message : un message de Docker ou de
  PostgreSQL peut citer une donnée. Le détail est dans le diagnostic.
- `support/champs.txt` n'entre pas dans la liste des fichiers exigés du programme
  (`$script:CogesProgrammeFiles`) : un programme sans la liste n'envoie rien, et le dit au
  journal. Les tests du lot 3 restent inchangés.

## Limites

- Healthchecks.io est un service tiers, hébergé hors d'Afrique de l'Ouest. Il reçoit la liste
  ci-dessus et l'adresse IP publique de la box du client. L'annexe du contrat le dit, et l'auto-
  hébergement reste possible sans changer le PC (les adresses sont dans `support.json`).
- L'heure de `envoye_le` est celle du PC, pas une heure de confiance.
- Aucun envoi n'est signé : quelqu'un qui connaît une adresse de ping peut envoyer un faux
  « je vais bien ». C'est pour cela que les adresses sont traitées comme des secrets.
- Rien n'est testé sur un vrai Windows en CI : `Get-AppxPackage` (Assistance rapide),
  `wsl --version`, `Get-ScheduledTaskInfo`, l'Explorateur ouvert sur le zip et l'envoi par
  Windows PowerShell 5.1 sont dans la liste « à vérifier sur Windows »
  (`docs/prompt-sur-site/README.md`).

## Conséquences

Un incident chez un client (sauvegarde ratée, retour arrière, PC muet) arrive chez CoGes sans
que le commerçant appelle. Le diagnostic se lit à distance, et la prise en main se fait avec
son accord. Le sur-site est complet côté code ; il reste la vérification sur Windows des lots 5
et 6.
