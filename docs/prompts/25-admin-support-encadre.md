# Prompt 25 — Lot admin 4 : accès support encadré à une entreprise

Branche `feat/admin-support-access`, depuis `main` à jour, après le lot admin 1 (prompt 22) — idéalement après le lot admin 2 (prompt 23) pour réutiliser le mécanisme de bandeau. C'est le lot le plus sensible de toute l'interface d'administration : il ouvre, de façon encadrée et temporaire, la seule porte vers les données commerciales d'une entreprise depuis un compte plateforme. À détailler et valider en profondeur avant de coder — plus que les autres lots.

```
Lot admin 4 — Accès support encadré (branche feat/admin-support-access, depuis main à jour,
après le prompt 22). Règles habituelles : ADR aux prochains numéros libres, tests d'abord,
aucun service payant, ne jamais ouvrir ni commiter .env, deploy/.env.preprod ni
backend/.vercel/. Résumé en français à la fin, questions ouvertes par AskUserQuestion.

Principe directeur, à ne jamais affaiblir pour « simplifier » : ce lot n'ajoute NI rôle
PostgreSQL privilégié NI contournement de RLS. Une session de support donne à un compte
plateforme un accès qui passe par EXACTEMENT le même chemin qu'un utilisateur normal de
l'entreprise (coges_app, RLS normale, SET LOCAL app.company_id), limité en lecture seule,
limité dans le temps, et jamais sans trace. Si une implémentation proposée ajoute un GRANT ou
une politique RLS supplémentaire pour ce lot, arrête-toi et repose la question — ce n'est pas
ce qui est demandé.

[DEMANDER] avant de coder : lequel des deux déclenchements ci-dessous retenir pour commencer
(ou les deux).
(a) Consentement du gérant : le gérant d'une entreprise reçoit une demande (depuis
    l'application commerçant, ou par un lien envoyé autrement) et l'accepte explicitement pour
    une durée donnée. Le plus respectueux, mais suppose que le gérant soit disponible et
    comprenne la demande.
(b) Bris de glace justifié : un compte plateforme déclenche l'accès unilatéralement, avec un
    texte de justification obligatoire (« pourquoi »), sans attendre le gérant — pour les
    urgences où il n'est pas joignable. Plus rapide, mais c'est la voie qu'il faut le plus
    encadrer (durée courte par défaut, audit renforcé, notification immédiate).
Recommandation : construire (b) en premier (plus simple, couvre déjà le cas d'usage « un
commerçant signale un problème par téléphone et on doit regarder »), prévoir la table et les
endpoints de façon à ce que (a) s'ajoute par la suite sans tout refaire (un champ
granted_by_user_id nullable suffit : rempli pour (a), NULL pour (b)).

1. Modèle de données (migration au prochain numéro libre)
   - Table support_sessions (plateforme, hors RLS tenant) : id, company_id, platform_user_id,
     justification (texte, obligatoire pour un bris de glace, facultatif si accordé par le
     gérant), granted_by_user_id (nullable, référence users de l'entreprise si consentement),
     started_at, expires_at (started_at + durée par défaut, voir section 2), ended_at
     (nullable, rempli à la fermeture manuelle ou à l'expiration), created_at.
   - Aucune donnée commerciale ne transite par cette table : seulement le fait qu'un accès a eu
     lieu, par qui, pourquoi, quand.

2. Émission d'un jeton de support
   - POST /api/v1/platform/companies/{id}/support-sessions (justification obligatoire) : crée
     la ligne, émet un jeton à courte durée de vie (même mécanisme JWT que l'auth commerçant,
     mais avec une revendication via_support_session=true et un rôle synthétique en LECTURE
     SEULE — jamais gérant, jamais vendeur, jamais comptable ; un rôle dédié support_readonly
     dont les permissions sont un sous-ensemble explicite des permissions existantes, défini
     dans le même registre RBAC que les trois rôles actuels). Durée par défaut : [DEMANDER] le
     nombre d'heures (proposition : 2 h, comme évoqué dans la proposition d'administration).
   - Audit critique à la création (platform_audit_logs ET, cette fois, une entrée dans
     l'audit_logs DE L'ENTREPRISE elle-même — l'entreprise doit pouvoir voir dans son propre
     journal d'activité qu'un accès support a eu lieu, pas seulement la plateforme).
   - DELETE /api/v1/platform/support-sessions/{id} : clôture manuelle avant expiration. Audit
     critique des deux côtés, comme à l'ouverture.
   - Expiration : le jeton cesse de fonctionner à expires_at sans action nécessaire (vérifié à
     chaque requête, comme pour un jeton normal expiré) ; une tâche de nuit (beat.py, registre du
     lot C) ferme proprement les lignes expirées non closes (ended_at = expires_at) pour que la
     liste des sessions actives reste exacte.

3. Lecture seule, vraiment
   - Le rôle support_readonly ne porte AUCUNE permission d'écriture, vérifié par un test qui
     énumère toutes les routes POST/PUT/PATCH/DELETE du tenant et confirme qu'aucune n'accepte
     ce rôle (sur le modèle du registre de permissions existant, décision 0075).
   - Les routes qui, aujourd'hui, filtrent déjà par rôle (gérant seul, etc.) continuent de
     refuser support_readonly exactement comme elles refuseraient un vendeur sur une route
     réservée au gérant — pas de cas particulier à coder, juste s'assurer que le nouveau rôle
     n'est ajouté à aucune liste de permissions existante par erreur.

4. Visibilité côté commerçant
   - Bandeau dans l'application commerçant (réutilise le mécanisme de bandeau du prompt 23 côté
     plateforme ou un équivalent côté front commerçant, à ajuster selon ce qui existe) : « Accès
     support actif depuis HH:MM, par l'équipe CoGes, jusqu'à HH:MM » — visible par tous les
     utilisateurs de l'entreprise pendant toute la durée de la session, pas seulement le gérant.
   - Entrée correspondante dans le journal d'activité de l'entreprise (section 2) : visible dans
     l'écran existant (décision 0053), avec la justification si elle a été fournie.

5. Interface web (frontend-admin/)
   - Dans l'écran détail d'une entreprise (prompt 22) : bouton « Ouvrir un accès support »
     (formulaire : justification obligatoire, durée éventuellement modifiable dans une limite
     maximale codée en dur), et si une session est active, son compte à rebours avec un bouton
     pour la fermer avant l'heure.
   - Une fois la session ouverte, l'interface plateforme doit donner un moyen de VOIR les
     données de l'entreprise avec ce jeton — [DEMANDER] : une vue dédiée dans frontend-admin/
     qui consomme l'API tenant en lecture seule avec ce jeton (duplique une partie de
     l'affichage du front commerçant), ou une redirection temporaire vers le front commerçant
     lui-même avec ce jeton de support. Recommandation : redirection vers le front commerçant
     existant — évite de dupliquer des écrans entiers (ventes, stock, finance) dans
     frontend-admin/ ; le front commerçant n'a rien de spécial à coder puisqu'il consomme déjà
     un jeton et un rôle comme un autre, il affichera simplement moins (pas de bouton
     d'écriture) si le rôle le permet déjà par construction.

6. Tests
   - Un jeton de support expiré est refusé à la requête suivante, pas seulement à une nouvelle
     connexion (même test que pour l'expiration des mots de passe provisoires, lot A).
   - Aucune route d'écriture n'accepte support_readonly (section 3).
   - Le bandeau et le journal d'activité de l'entreprise reflètent une session active, puis son
     absence après fermeture ou expiration.
   - Isolation : un jeton de support pour l'entreprise A ne donne accès à rien de l'entreprise B
     (même test que n'importe quel jeton tenant, section déjà couverte par les tests
     d'isolation existants — vérifie juste que le nouveau rôle est bien inclus dans leur
     périmètre de test, pas oublié).
   - Scénario complet end-to-end : bris de glace déclenché, bandeau visible côté commerçant,
     lecture de données réelles possible, écriture refusée, fermeture manuelle, bandeau
     disparaît, entrée dans les deux journaux (plateforme et entreprise).

Fin du lot : suite backend complète, ruff, mypy, make front-check sur les deux fronts, e2e du
scénario complet de la section 6. Avant de fusionner, demande une relecture humaine de ce lot en
particulier (la justification dans l'ADR doit être lisible par quelqu'un qui n'a pas suivi le
développement) — c'est le lot qui touche le plus directement à la confiance des commerçants.
```

## Ce que le propriétaire fait lui-même

1. Trancher les questions `AskUserQuestion` (déclenchement à construire en premier, durée par défaut, vue dédiée vs redirection) avant que l'agent commence.
2. Relire personnellement ce lot avant de le fusionner en production, comme le prompt le demande.
