# Configurer l'envoi d'e-mails

CoGes envoie ses e-mails par n'importe quel relais SMTP (ADR 0089) : vérification et
bienvenue de l'inscription (ADR 0118), invitations de l'équipe, alertes. Sans SMTP, rien ne
part et rien n'échoue : les demandes d'inscription passent alors toutes par l'équipe.

## 1. Choisir un relais

Un relais avec une offre gratuite de quelques centaines d'e-mails par jour suffit au
lancement. Créer une adresse d'envoi du type `noreply@coges.app`.

## 2. DNS chez Cloudflare (pour ne pas arriver en indésirables)

Le relais fournit les valeurs exactes ; on les recopie dans Cloudflare → `coges.app` →
**DNS** → *Add record*, **sans proxy** (nuage gris) :

| Type | Nom | Contenu | Rôle |
|---|---|---|---|
| TXT | `@` | `v=spf1 include:<domaine du relais> ~all` | **SPF** : le relais a le droit d'envoyer pour coges.app. Un seul enregistrement SPF : s'il en existe déjà un, y ajouter l'`include:`. |
| TXT ou CNAME | `<sélecteur>._domainkey` | clé fournie par le relais | **DKIM** : signature de chaque e-mail. |
| TXT | `_dmarc` | `v=DMARC1; p=none; rua=mailto:<adresse de l'équipe>` | **DMARC** : ce que font les boîtes des messages non signés. Commencer à `p=none`, passer à `p=quarantine` après deux semaines de rapports propres. |

Attendre que le relais affiche le domaine « vérifié ».

## 3. Variables dans `/etc/coges/coges.env`

```bash
COGES_SMTP_HOST=smtp.<relais>
COGES_SMTP_PORT=587
COGES_SMTP_USERNAME=<identifiant>
COGES_SMTP_PASSWORD=<secret>
COGES_SMTP_FROM=CoGes <noreply@coges.app>
COGES_PLATFORM_ALERT_EMAIL=<adresse de l'équipe>
```

Puis redéployer la version en place (`sudo -u deploy /opt/coges/deploy.sh production
<version>`) : l'API, le worker et le beat relisent l'environnement.

## 4. Vérifier

- S'inscrire sur la **préproduction** avec une vraie adresse Gmail **et** une Outlook :
  l'e-mail doit arriver dans la boîte de réception, pas dans les indésirables. Dans Gmail,
  « Afficher l'original » doit dire `SPF: PASS`, `DKIM: PASS`, `DMARC: PASS`.
- L'administration (Demandes) n'affiche plus l'avertissement « L'envoi d'e-mails n'est pas
  configuré ».
