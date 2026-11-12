# 0120 — Notifications sur le téléphone (Web Push)

- **Date** : 2026-11-11
- **Phase** : groupe 5, bloc N (prompt 36, branche `phase/36-n-notifications`)
- **Statut** : acceptée (complète 0032, 0057, 0059 et 0102)
- **Décideur** : propriétaire (téléphone même fermé, après « Activer » ; écran verrouillé
  « détail utile, sans aucun montant », 11 novembre 2026) ; utilisateur via AskUserQuestion
  (bibliothèque, personne qui agit, plafonds) ; plan validé avant le code

## Contexte
Les alertes n'existaient que dans la cloche (ADR 0032) : un gérant qui ne regarde pas
l'écran ne voit ni un stock épuisé ni une vente annulée. Le propriétaire veut les recevoir
sur le téléphone, application fermée, sans exposer d'argent sur un écran verrouillé posé
sur le comptoir. Services externes autorisés pour ce bloc : ceux des navigateurs.

## Options envisagées
1. **http-ece 1.2.1 + py-vapid 1.9.6 + httpx (retenue)** : les deux briques de pywebpush
   (même auteur, Mozilla ; MIT et MPL-2.0), versions figées, ne dépendant que de
   `cryptography`, envoi par le client HTTP déjà présent.
2. pywebpush 2.5.0 : moins de code, mais `aiohttp` et `requests` en plus dans l'image, et
   `cryptography>=47`.
3. Chiffrement RFC 8291 et jeton VAPID écrits à la main : aucune dépendance, du chiffrement
   maison à maintenir.

## Décision
**Clés** : `COGES_VAPID_PUBLIC_KEY`, `COGES_VAPID_PRIVATE_KEY`, `COGES_VAPID_SUBJECT`, les
trois ou aucune, base64url (P-256 brute), tirées par `python -m app.cli
generate-vapid-keys`. L'API refuse de démarrer avec une paire incohérente (`config.py`) ;
`check_runtime_env.py` refuse une pile à moitié configurée. Sans clés, `GET
/notifications/push/config` rend `public_key: null`, le menu n'a pas d'entrée, rien ne part.
La clé privée reste sur le serveur (API et worker) ; la changer désabonne tous les appareils.

**Données** (révision 0041) : `push_subscriptions` sous RLS FORCE, FK composite vers
`users`, un abonnement vivant par `(entreprise, endpoint)`. `coges_app` n'a pas de DELETE :
un abonnement s'**arrête** (`disabled_at`, `disabled_reason` ∈ `unsubscribed`, `logout`,
`gone`, `replaced`, `failures`). T36 ne change pas. 5 appareils vivants par personne au plus
(`COGES_PUSH_MAX_DEVICES`) : le sixième arrête le plus ancien. Le même téléphone qui change
de compte dans la boutique passe à la nouvelle personne.

**Adresses** : un `endpoint` vient du client ; le worker ne poste **que** chez Google (FCM),
Mozilla, Apple et Microsoft (`webpush.PUSH_HOSTS`, HTTPS, port 443, sans identifiants),
contrôlé à l'abonnement (422 `push_endpoint_refused`) et au moment d'envoyer. Sans cela, un
client ferait poster le worker vers une adresse interne (requête forgée côté serveur).

**API** (module `notifications`, pour soi seul, `notifications:read`) : `GET
/push/config`, `GET /push/subscriptions` (appareils, sans les clés), `POST
/push/subscriptions` (201 ; 409 `push_unavailable` sans clés),
`POST /push/subscriptions/remove` (204, même pour une adresse inconnue ; `?logout=true`).

**Envoi** : `notify()` exige désormais `push` (un texte par type, `notifications/push.py`,
exposé par la façade en `push_texts`) ; le texte est gardé dans `data["push"]`. Les
alertes créées sont enfilées **après le COMMIT** (`on_commit` → `notifications.push_deliver`) :
une alerte annulée avec sa transaction ne sonne jamais. La tâche lit (une transaction),
poste sans transaction ouverte, puis note les réponses (une autre) : 2xx = appareil à jour,
404 ou 410 = abonnement arrêté (`gone`), autre échec compté, arrêté au dixième de suite.
Message chiffré `aes128gcm`, `TTL` 12 h, `Urgency: normal`, jeton VAPID de 12 h.

**Contenu** : titre, texte et chemin écrits par le serveur, sans montant ni numéro de
téléphone : « Riz 25 kg : stock bas (3 sacs) », « Riz 25 kg est épuisé », « Moussa D.
n'a pas payé à temps » (l'exemple du prompt, « arrivée à échéance », sort du lexique de l'ADR
0069 : les mots de la cloche, ADR 0074), « Vente n° 42 annulée par Awa » (ou « corrigée »), « Un
conseil important vous attend » (le détail d'un conseil est souvent chiffré), « Connexions
échouées sur le compte de … », « Fin de l'essai dans 3 jours », « Accès support ouvert par
l'équipe CoGes ». `safe_message` revérifie avant l'envoi : un texte où paraît une somme
(nom d'article « Sac 5 000 F ») ou un numéro est remplacé par « Nouvelle alerte dans
CoGes ». Le chemin est relatif à l'application, vérifié côté worker et côté service worker
(sinon `/notifications`).

**Rafale** : au-delà de 3 alertes en une minute pour une personne, un seul message « N
nouvelles alertes » vers `/notifications`. Toutes les notifications portent le même `tag`
(`coges-alertes`, `renotify`) : l'appareil n'en montre qu'une, la dernière ; la cloche
garde tout.

**Personne qui agit** (choix de l'utilisateur) : pas de notification à qui a annulé ou
corrigé la vente (`SELF_SILENT_TYPES`, `sale.cancelled` porte `cancelled_by_user_id`).
Le stock bas ou épuisé part toujours, même après sa propre vente.

**Plafond** : 30 notifications par personne et par heure (`COGES_PUSH_MAX_PER_HOUR`), clé
Redis `coges:<entreprise>:push:<personne>:<heure>` (2 h). Sans Redis, on laisse passer.

**Front** : écran `/account/notifications` (menu du compte, seulement si le serveur a ses
clés) ; la permission n'est demandée qu'à l'appui sur « Activer » ; refus du navigateur :
comment réautoriser ; iPhone et iPad hors écran d'accueil : l'installer d'abord (iOS 16.4+) ;
« Désactiver ». La déconnexion arrête l'abonnement de l'appareil au serveur (avec le jeton
encore valide) puis dans le navigateur. Service worker : `push` et `notificationclick`
ajoutés, aucun cache, aucun appel réseau ; le clic navigue l'onglet ouvert (puis le met
devant) ou ouvre CoGes. L'administration n'est pas concernée.

## Conséquences
- `worker` et `api` reçoivent les trois variables (`deploy/vps/docker-compose.yml`) ; le
  réseau `jobs` du worker sort déjà sur Internet (SMTP).
- `pushsubscriptionchange` (abonnement renouvelé par le navigateur) n'est pas traité : le
  service répond 410 à l'ancienne adresse, l'abonnement s'arrête, l'écran redit « désactivé »
  et la personne réappuie.
- Les trois premières alertes d'une rafale partent avant que la quatrième ne la regroupe.
- e2e : le Chromium de test ne joint pas FCM ; l'abonnement du navigateur y est simulé et le
  push livré par le protocole DevTools. L'envoi réel (chiffrement relu par la clé de
  l'appareil, 410, rafale, plafond, personne qui agit) est prouvé par
  `tests/integration/test_push_notifications.py`.
- Tests : `tests/unit/test_push_texts.py` (chaque type sans montant, détecteur, chemins,
  hôtes, chiffrement relu, VAPID), `test_push_notifications.py`, `test_deploy_scripts.py`
  (clés VAPID), Vitest `lib/push.test.ts`, `lib/pwa/sw-push.test.ts`, e2e `push.spec.ts`
  (build de production).
