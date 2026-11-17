# Installation sur site — les six lots

CoGes sur le PC d'un client : une société, un poste fixe sous Windows 11, le navigateur du
PC ouvre `http://localhost`. Règle d'or : **ajouter, ne rien modifier** (ADR 0124) ; les
utilisateurs actuels ne voient aucune différence.

| Lot | Contenu | Résultat attendu | État |
|---|---|---|---|
| 1 | Assemblage : compose, Caddyfile, réglages, contrôle, migrations locales (`01-assemblage.md`) | CoGes démarre sur `http://localhost` | ✅ code et CI Linux (ADR 0124) ; **à vérifier sur Windows** par le propriétaire |
| 2 | Commande `activate-license` et premier démarrage | Une société créée, licence activée | ⬜ |
| 3 | Script d'installation Windows | Installation en une commande | ⬜ |
| 4 | Sauvegarde et restauration locales | Une panne simulée, données retrouvées | ⬜ |
| 5 | Mises à jour à distance et retour arrière | Passage d'une version à la suivante sans se déplacer | ⬜ |
| 6 | Support à distance et journaux | Intervention sans se déplacer | ⬜ |

Guide d'installation : `docs/runbooks/sur-site.md`. Décision : `docs/decisions/0124-assemblage-sur-site.md`.

## Où sont les fichiers

| Dossier | Rôle |
|---|---|
| `deploy/onprem/` | ce qui est livré au client, autonome : compose, Caddyfile, amorçage des rôles, modèle de réglages, contrôles |
| `deploy/onprem-ci/` | vérification de bout en bout (`verifier.sh`, parcours Chromium, relecture des données) ; jamais livré |
| `.github/workflows/onprem.yml` | workflow « Sur site », à part de la CI et du déploiement |
| `backend/tests/unit/test_onprem_*.py` | tests sur les fichiers versionnés |

## Lot 1 — à vérifier sur la machine Windows

La CI tourne sous Linux. Reste à constater, sur un PC Windows 11 avec Docker Desktop (WSL 2),
en suivant `docs/runbooks/sur-site.md` :

1. **Docker Desktop et WSL 2** : installation, virtualisation activée, `docker version` et
   `docker compose version` répondent dans PowerShell.
2. **Montage des fichiers** depuis `C:\CoGes\programme` : Caddy lit son `Caddyfile` et la
   page de maintenance ; PostgreSQL exécute `postgres-init\01-roles.sql` à la première
   mise en route (les rôles existent, `migrate` passe). Vérifier que les fichiers sont
   restés en LF après copie.
3. **Le contrôle des réglages** lancé par `docker run` avec les deux dossiers montés
   (`C:\CoGes\programme` et `C:\CoGes\reglages`) : il lit `coges.env`, y compris enregistré
   par le Bloc-notes.
4. **autoheal et le socket Docker** : le conteneur `autoheal` démarre avec
   `/var/run/docker.sock` monté et reste « healthy » ; arrêter le processus d'un service
   de l'intérieur et constater qu'il est relancé.
5. **Port 80** : libre ou non sur ce PC ; si non, la procédure « Le port 80 est déjà
   pris » (port 8080) fonctionne, connexion comprise.
6. **Navigateur Edge puis Chrome** sur `http://localhost` : connexion du gérant, la page
   rechargée reste connectée (cookie `Secure`), une vente s'enregistre, l'application
   propose de s'installer (service worker).
7. **Depuis un autre appareil du magasin**, `http://<adresse du PC>` ne répond pas.
8. **Redémarrage du PC** : après l'ouverture de la session Windows, Docker Desktop relance
   CoGes seul ; la société et les ventes sont là. Noter le temps avant que
   `http://localhost` réponde.
9. **Coupure brutale** (éteindre le PC par le bouton, sur un PC de test) : au retour,
   PostgreSQL se répare seul et les données sont là.
10. **Mémoire** : onglet de Docker Desktop ou `docker stats --no-stream`, au repos et
    pendant une vente (attendu : environ 750 Mo, plafonds à 2,7 Go).
11. **Mise à jour à la main** d'une version à la suivante avec la procédure du guide, puis
    retour arrière.
12. **Veille de Windows** : le PC mis en veille puis réveillé, CoGes répond de nouveau.

À rapporter : ce qui marche, les messages d'erreur exacts, la mémoire utilisée.
