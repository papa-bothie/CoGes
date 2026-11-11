# Ouvrir ou fermer les inscriptions

Inscription libre-service (ADR 0118). Fermée par défaut : aucun bouton « Créer ma
boutique », les routes publiques répondent 404, rien n'est écrit.

## Avant la première ouverture (une fois)

1. **Rôle `coges_signup` sur Neon**, préproduction puis production, en `neondb_owner`,
   **avant** la migration 0039 (déjà fait si l'image ≥ lot 30 tourne) :
   `psql "$NEONDB_OWNER_DSN" -f deploy/sql/create_signup_role.sql`
2. **Clé du HMAC** dans `/etc/coges/coges.env` (32 caractères au moins), à garder comme les
   autres secrets :
   ```bash
   echo "COGES_SIGNUP_IP_HASH_KEY=$(openssl rand -hex 32)" | sudo tee -a /etc/coges/coges.env
   ```
3. **E-mails** (facultatif, mais sans eux toute demande passe par l'équipe) :
   `docs/runbooks/emails.md`.
4. **Le chemin sans e-mail** : qui traite les demandes, à quelles heures (week-end compris),
   les deux messages types (`docs/runbooks/demandes-inscription.md`).
5. **Tester sur la préproduction** les deux chemins avec vos propres coordonnées.

## Ouvrir

```bash
sudo sed -i 's/^COGES_SIGNUP_ENABLED=.*/COGES_SIGNUP_ENABLED=true/' /etc/coges/coges.env
sudo -u deploy /opt/coges/deploy.sh production <version en place>   # relit l'environnement
```

`check_runtime_env.py` refuse de démarrer si la clé manque. Le bouton paraît sur la vitrine
et sur la connexion **dans les 5 minutes** (pages relues par le serveur toutes les 5 minutes).

## Fermer (en cas d'abus, par exemple)

Même commande avec `false`, puis le même redéploiement. Les routes publiques répondent 404
dès le redémarrage de l'API ; le bouton disparaît dans les 5 minutes. Les demandes déjà
reçues restent dans l'administration, et un lien déjà envoyé ne marche plus tant que c'est
fermé.

## Limites (réglages `COGES_SIGNUP_*`, valeurs par défaut)

Par adresse IP 5 par heure et 20 par jour ; par numéro 3 par jour ; par e-mail 3 par jour ;
30 demandes par heure en tout ; 50 boutiques par jour ouvertes par le lien e-mail —
au-delà, les demandes passent par l'équipe et vous recevez une alerte. Si Redis est en
panne, les inscriptions sont refusées (message « momentanément indisponibles »).
