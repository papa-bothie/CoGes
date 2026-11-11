# Notifications sur le téléphone (Web Push)

Les alertes de la cloche partent aussi sur le téléphone, même CoGes fermé, pour chaque
personne qui a touché « Activer les notifications » (menu du compte) puis « Autoriser »
(ADR 0120). L'écran verrouillé montre le détail utile, **jamais un montant**. Sans clés VAPID,
le bouton n'apparaît pas et rien ne part : c'est l'état par défaut.

## 1. Tirer la paire de clés (une fois)

Sur le poste, dans le dépôt :

```bash
uv run --directory backend python -m app.cli generate-vapid-keys
```

La commande affiche trois lignes et n'écrit rien sur disque. Ne pas la coller dans une
conversation ni dans git.

## 2. Les poser dans `/etc/coges/coges.env` (production)

```bash
COGES_VAPID_PUBLIC_KEY=<ligne 1>
COGES_VAPID_PRIVATE_KEY=<ligne 2>     # SECRET : ne quitte jamais le serveur
COGES_VAPID_SUBJECT=mailto:<adresse de l'équipe>
```

Les trois ensemble, ou aucune : `check_runtime_env.py` refuse le déploiement d'une pile à
moitié configurée, et l'API refuse de démarrer si les deux clés ne vont pas ensemble.
L'API (clé publique servie au navigateur) et le worker (signature) les reçoivent par
`deploy/vps/docker-compose.yml`. Redéployer pour qu'elles soient lues.

Garder la clé privée avec les autres secrets (comme la clé `age` de la sauvegarde). **La
changer désabonne tous les téléphones** : chacun devra retoucher « Activer ».

## 3. Vérifier après le déploiement

1. Sur un téléphone Android (Chrome) : menu du compte → « Notifications sur le
   téléphone » → « Activer les notifications » → « Autoriser ».
2. Sur iPhone : CoGes doit d'abord être **installé sur l'écran d'accueil** (Safari →
   Partager → « Sur l'écran d'accueil », iOS 16.4 ou plus), puis ouvert depuis son icône.
3. Faire baisser un stock sous son seuil (une vente suffit) : la notification arrive,
   téléphone verrouillé, sans montant ; la toucher ouvre la livraison de l'article.

## 4. Si rien n'arrive

- Le worker doit tourner (`make ops-status`) : c'est lui qui envoie, après le COMMIT.
- Ses journaux disent « Plafond horaire de notifications atteint » au-delà de
  30 notifications par personne et par heure (`COGES_PUSH_MAX_PER_HOUR`).
- Un appareil qui a désinstallé l'application ou retiré l'autorisation est arrêté tout
  seul (réponse 404 ou 410 du service de push) ; la personne réactive sur son écran.
- Le téléphone en économie d'énergie peut retarder les notifications : c'est le système,
  pas CoGes.

## Ce qui part, et vers où

Seuls les services de push des navigateurs reçoivent un message, et il est chiffré pour
l'appareil : Google (Chrome, Android), Mozilla (Firefox), Apple (Safari, iPhone), Microsoft
(Edge). Le serveur refuse toute autre adresse d'abonnement. Aucune somme, aucun numéro de
téléphone ; « Vente n° 42 annulée par Awa », « Riz 25 kg est épuisé ».
